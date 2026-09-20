from collections import defaultdict

from joymedia.joymedia.report.analytics import get_attempt_analytics


COLUMNS = [
	{"fieldname": "source", "label": "Source", "fieldtype": "Data", "width": 120},
	{"fieldname": "workflow_version", "label": "Workflow Version", "fieldtype": "Link", "options": "Workflow Version", "width": 150},
	{"fieldname": "prompt_template_version", "label": "Prompt Template Version", "fieldtype": "Link", "options": "Prompt Template Version", "width": 170},
	{"fieldname": "comfyui_worker", "label": "ComfyUI Worker", "fieldtype": "Link", "options": "ComfyUI Worker", "width": 140},
	{"fieldname": "failure_class", "label": "Failure Class", "fieldtype": "Data", "width": 160},
	{"fieldname": "retry_reason", "label": "Retry Reason", "fieldtype": "Data", "width": 170},
	{"fieldname": "count", "label": "Count", "fieldtype": "Int", "width": 80},
]


def execute(filters=None):
	attempts, reviews = get_attempt_analytics(filters)
	attempts_by_name = {attempt.name: attempt for attempt in attempts}
	artifact_names = {review.generation_artifact for review in reviews if review.generation_artifact}
	artifacts = frappe.get_all(
		"Generation Artifact",
		filters={"name": ["in", list(artifact_names)]} if artifact_names else {"name": ["in", [""]]},
		fields=["name", "generation_attempt"],
	)
	attempt_by_artifact = {artifact.name: artifact.generation_attempt for artifact in artifacts}
	buckets = defaultdict(int)

	for attempt in attempts:
		if attempt.failure_class:
			buckets[
				(
					"Execution Attempt",
					attempt.workflow_version or "Unassigned",
					attempt.prompt_template_version or "Unassigned",
					attempt.comfyui_worker or "Unassigned",
					attempt.failure_class,
					attempt.retry_reason or "",
				)
			] += 1

	for review in reviews:
		attempt = attempts_by_name.get(attempt_by_artifact.get(review.generation_artifact))
		if not attempt or review.status not in ("Rejected", "Needs Revision") or not review.failure_class:
			continue
		buckets[
			(
				"Quality Review",
				attempt.workflow_version or "Unassigned",
				attempt.prompt_template_version or "Unassigned",
				attempt.comfyui_worker or "Unassigned",
				review.failure_class,
				attempt.retry_reason or "",
			)
		] += 1

	return COLUMNS, [
		{
			"source": source,
			"workflow_version": workflow_version,
			"prompt_template_version": prompt_template_version,
			"comfyui_worker": worker,
			"failure_class": failure_class,
			"retry_reason": retry_reason,
			"count": count,
		}
		for (source, workflow_version, prompt_template_version, worker, failure_class, retry_reason), count in sorted(
			buckets.items(), key=lambda item: item[1], reverse=True
		)
	]
