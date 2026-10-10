from math import ceil

import frappe
from frappe.utils import add_days, get_datetime, getdate


def get_attempt_analytics(filters=None):
	filters = frappe._dict(filters or {})
	attempt_filters = {}
	if filters.from_date:
		attempt_filters["creation"] = [">=", getdate(filters.from_date)]
	if filters.to_date:
		attempt_filters.setdefault("creation", ["<", add_days(getdate(filters.to_date), 1)])
		if attempt_filters["creation"][0] == ">=":
			attempt_filters["creation"] = [
				"between",
				[attempt_filters["creation"][1], add_days(getdate(filters.to_date), 1)],
			]

	attempts = frappe.get_all(
		"Generation Attempt",
		filters=attempt_filters,
		fields=[
			"name",
			"generation_task",
			"status",
			"retry_of",
			"retry_reason",
			"failure_class",
			"runtime_seconds",
			"queued_at",
			"started_at",
		],
	)
	job_names = {attempt.generation_task for attempt in attempts if attempt.generation_task}
	jobs = frappe.get_all(
		"Generation Task",
		filters={"name": ["in", list(job_names)]} if job_names else {"name": ["in", [""]]},
		fields=["name", "workflow", "shot"],
	)
	jobs_by_name = {job.name: job for job in jobs}
	shot_names = {job.shot for job in jobs if job.shot}
	shots = frappe.get_all(
		"Shot",
		filters={"name": ["in", list(shot_names)]} if shot_names else {"name": ["in", [""]]},
		fields=["name", "selected_output_asset_version", "review_status"],
	)
	selected_outputs_by_shot = {
		shot.name: shot.selected_output_asset_version for shot in shots if shot.selected_output_asset_version
	}
	review_status_by_shot = {shot.name: shot.review_status for shot in shots}

	# Collect human QA verdicts from Shot Review records keyed by generation_attempt.
	attempt_names = [attempt.name for attempt in attempts]
	shot_reviews = frappe.get_all(
		"Shot Review",
		filters={"generation_attempt": ["in", attempt_names]} if attempt_names else {"name": ["in", [""]]},
		fields=["generation_attempt", "verdict"],
		order_by="reviewed_at desc",
	)
	# Most recent review per attempt wins.
	review_verdict_by_attempt = {}
	for rev in reversed(shot_reviews):
		review_verdict_by_attempt[rev.generation_attempt] = rev.verdict

	# A reviewer selects an Asset Version, not the transient Generation Artifact.
	# Asset Version.source_generation_attempt is the durable lineage link for every
	# output type (image, video, or audio), including composed shot outputs.
	output_versions = frappe.get_all(
		"Asset Version",
		filters={"source_generation_attempt": ["in", attempt_names]} if attempt_names else {"name": ["in", [""]]},
		fields=["name", "source_generation_attempt"],
	)
	source_attempt_by_output = {
		version.name: version.source_generation_attempt
		for version in output_versions
		if version.source_generation_attempt
	}
	enriched_attempts = []
	for attempt in attempts:
		job = jobs_by_name.get(attempt.generation_task)
		attempt.workflow = job.workflow if job else None
		attempt.selected_output = _is_selected_output(
			attempt.name,
			job.shot if job else None,
			selected_outputs_by_shot,
			source_attempt_by_output,
		)
		# Use real human QA verdict when available; fall back to implicit proxy.
		qa_verdict = review_verdict_by_attempt.get(attempt.name)
		approved, reviewed = _review_outcome(qa_verdict, attempt.selected_output)
		attempt.review_outcome = {"approved": approved, "reviewed": reviewed}
		if filters.workflow and attempt.workflow != filters.workflow:
			continue
		enriched_attempts.append(attempt)

	return enriched_attempts, []


def _is_selected_output(attempt_name, shot_name, selected_outputs_by_shot, source_attempt_by_output):
	"""Whether this attempt produced the Asset Version currently selected for its shot."""
	selected_output = selected_outputs_by_shot.get(shot_name)
	return bool(selected_output and source_attempt_by_output.get(selected_output) == attempt_name)


def _review_outcome(qa_verdict, selected_output):
	"""Use explicit QA when present; selection is the legacy completion proxy."""
	if qa_verdict:
		return qa_verdict == "Approved", True
	return bool(selected_output), bool(selected_output)


def percentile_95(values):
	values = sorted(value for value in values if value is not None)
	if not values:
		return None
	return values[ceil(len(values) * 0.95) - 1]


def queue_wait_seconds(attempt):
	if not attempt.queued_at or not attempt.started_at:
		return None
	return max(0, (get_datetime(attempt.started_at) - get_datetime(attempt.queued_at)).total_seconds())


def percent(numerator, denominator):
	return round(numerator / denominator * 100, 2) if denominator else None
