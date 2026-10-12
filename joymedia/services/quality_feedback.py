"""Turn aggregate QA failures into bounded guidance for future prompt snapshots."""

import frappe


MIN_SAMPLES = 3
MAX_GUIDANCE_ITEMS = 2


def prompt_guidance_for_workflow(workflow_name):
	"""Return evidence-backed corrective guidance for a workflow, if enough QA exists.

	This deliberately augments the immutable prompt snapshot for a new run rather
	than editing global templates or silently changing a user's chosen workflow.
	"""
	# Automated QA is advisory. Use the final explicit human verdict for each
	# immutable output, so a later approval supersedes an earlier rejection and
	# repeated reviews cannot over-weight one take.
	reviews = frappe.get_all(
		"Shot Review",
		filters={"review_kind": "Human"},
		fields=["shot", "output_asset_version", "rejection_category", "generation_attempt", "verdict"],
		order_by="reviewed_at desc, creation desc",
		limit_page_length=500,
	)
	rows = [
		review for review in _latest_human_reviews(reviews)
		if review.verdict in ("Rejected", "Needs Revision")
	]
	missing_attempt_outputs = [row.output_asset_version for row in rows if not row.generation_attempt]
	source_attempt_by_output = {
		row.name: row.source_generation_attempt
		for row in frappe.get_all(
			"Asset Version",
			filters={"name": ["in", missing_attempt_outputs]} if missing_attempt_outputs else {"name": ["in", [""]]},
			fields=["name", "source_generation_attempt"],
		)
	}
	for row in rows:
		row.generation_attempt = row.generation_attempt or source_attempt_by_output.get(row.output_asset_version)
	attempts = [row.generation_attempt for row in rows if row.generation_attempt]
	if not attempts:
		return []
	tasks = frappe.get_all(
		"Generation Attempt",
		filters={"name": ["in", attempts]},
		fields=["name", "generation_task"],
	)
	task_by_attempt = {row.name: row.generation_task for row in tasks}
	task_names = [name for name in task_by_attempt.values() if name]
	workflow_by_task = {
		row.name: row.workflow for row in frappe.get_all(
			"Generation Task", filters={"name": ["in", task_names]}, fields=["name", "workflow"]
		)
	}
	counts = {}
	for row in rows:
		if workflow_by_task.get(task_by_attempt.get(row.generation_attempt)) != workflow_name:
			continue
		category = row.rejection_category or "Visual Quality"
		counts[category] = counts.get(category, 0) + 1
	return [
		_guidance(category) for category, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
		if count >= MIN_SAMPLES
	][:MAX_GUIDANCE_ITEMS]


def _latest_human_reviews(reviews):
	"""Collapse review history to the final explicit human decision per output."""
	latest = {}
	for review in reviews:
		key = (review.shot, review.output_asset_version)
		if key not in latest and all(key):
			latest[key] = review
	return list(latest.values())


def append_quality_guidance(prompt, workflow_name):
	guidance = prompt_guidance_for_workflow(workflow_name)
	if not guidance:
		return prompt
	return f"{prompt.rstrip()}\n\nQUALITY REQUIREMENTS: {' '.join(guidance)}"


def _guidance(category):
	return {
		"Motion Artifacts": "Keep motion physically plausible; preserve anatomy, object geometry, and stable camera movement.",
		"Prompt Drift": "Follow the requested subject, setting, action, and framing exactly; do not introduce unrequested elements.",
		"Visual Quality": "Prioritize clean detail, coherent lighting, and artifact-free commercial imagery.",
		"Continuity Break": "Maintain identity, wardrobe, product geometry, lighting, and screen direction throughout the shot.",
		"Wrong Product": "Show the exact referenced product identity, shape, materials, colors, and branding without substitutions.",
	}.get(category, "Preserve the specified product identity and produce a clean, coherent commercial shot.")
