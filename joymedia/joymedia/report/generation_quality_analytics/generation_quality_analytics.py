from collections import defaultdict

from joymedia.joymedia.report.analytics import (
	get_attempt_analytics,
	percent,
	percentile_95,
	queue_wait_seconds,
)


COLUMNS = [
	{"fieldname": "workflow_version", "label": "Workflow Version", "fieldtype": "Link", "options": "Workflow Version", "width": 150},
	{"fieldname": "attempts", "label": "Attempts", "fieldtype": "Int", "width": 90},
	{"fieldname": "success_rate", "label": "Success Rate %", "fieldtype": "Percent", "width": 100},
	{"fieldname": "retry_rate", "label": "Retry Rate %", "fieldtype": "Percent", "width": 100},
	{"fieldname": "approval_rate", "label": "Approval Rate %", "fieldtype": "Percent", "width": 110},
	{"fieldname": "first_pass_approval_rate", "label": "First-Pass Approval %", "fieldtype": "Percent", "width": 135},
	{"fieldname": "avg_runtime_seconds", "label": "Avg Runtime (s)", "fieldtype": "Float", "width": 110},
	{"fieldname": "p95_runtime_seconds", "label": "p95 Runtime (s)", "fieldtype": "Float", "width": 110},
	{"fieldname": "avg_queue_wait_seconds", "label": "Avg Queue Wait (s)", "fieldtype": "Float", "width": 125},
	{"fieldname": "gpu_seconds_per_approved_shot", "label": "GPU Seconds / Approved Shot", "fieldtype": "Float", "width": 180},
]


def execute(filters=None):
	buckets = defaultdict(_new_bucket)
	for attempt in get_attempt_analytics(filters)[0]:
		key = attempt.workflow_version or "Unassigned"
		bucket = buckets[key]
		bucket["attempts"] += 1
		bucket["completed"] += attempt.status == "Completed"
		bucket["retries"] += bool(attempt.retry_of)
		bucket["reviewed"] += attempt.review_outcome["reviewed"]
		bucket["approved"] += attempt.review_outcome["approved"]
		if not attempt.retry_of and attempt.review_outcome["reviewed"]:
			bucket["first_pass_reviewed"] += 1
			bucket["first_pass_approved"] += attempt.review_outcome["approved"]
		if attempt.runtime_seconds is not None:
			bucket["runtime_seconds"].append(float(attempt.runtime_seconds))
		queue_wait = queue_wait_seconds(attempt)
		if queue_wait is not None:
			bucket["queue_wait_seconds"].append(queue_wait)
		if attempt.selected_output:
			if attempt.runtime_seconds is not None:
				bucket["approved_runtime_seconds"].append(float(attempt.runtime_seconds))

	data = []
	for workflow_version, bucket in sorted(buckets.items()):
		runtime_values = bucket["runtime_seconds"]
		queue_wait_values = bucket["queue_wait_seconds"]
		approved_runtime_values = bucket["approved_runtime_seconds"]
		data.append(
			{
				"workflow_version": workflow_version,
				"attempts": bucket["attempts"],
				"success_rate": percent(bucket["completed"], bucket["attempts"]),
				"retry_rate": percent(bucket["retries"], bucket["attempts"]),
				"approval_rate": percent(bucket["approved"], bucket["reviewed"]),
				"first_pass_approval_rate": percent(
					bucket["first_pass_approved"], bucket["first_pass_reviewed"]
				),
				"avg_runtime_seconds": _average(runtime_values),
				"p95_runtime_seconds": percentile_95(runtime_values),
				"avg_queue_wait_seconds": _average(queue_wait_values),
				"gpu_seconds_per_approved_shot": _average(approved_runtime_values),
			}
		)
	return COLUMNS, data


def _new_bucket():
	return {
		"attempts": 0,
		"completed": 0,
		"retries": 0,
		"reviewed": 0,
		"approved": 0,
		"first_pass_reviewed": 0,
		"first_pass_approved": 0,
		"runtime_seconds": [],
		"queue_wait_seconds": [],
		"approved_runtime_seconds": [],
	}


def _average(values):
	return round(sum(values) / len(values), 2) if values else None
