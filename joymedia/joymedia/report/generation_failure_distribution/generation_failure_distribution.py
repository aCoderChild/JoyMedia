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
	attempts, _ = get_attempt_analytics(filters)
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
