from collections import defaultdict

from joymedia.joymedia.report.analytics import (
	estimated_cost,
	get_attempt_analytics,
	percentile_95,
	queue_wait_seconds,
)


COLUMNS = [
	{"fieldname": "comfyui_worker", "label": "ComfyUI Worker", "fieldtype": "Link", "options": "ComfyUI Worker", "width": 160},
	{"fieldname": "attempts", "label": "Attempts", "fieldtype": "Int", "width": 90},
	{"fieldname": "completed_attempts", "label": "Completed", "fieldtype": "Int", "width": 100},
	{"fieldname": "failed_attempts", "label": "Failed", "fieldtype": "Int", "width": 80},
	{"fieldname": "approved_shots", "label": "Approved Shots", "fieldtype": "Int", "width": 115},
	{"fieldname": "total_runtime_seconds", "label": "Total Runtime (s)", "fieldtype": "Float", "width": 130},
	{"fieldname": "avg_runtime_seconds", "label": "Avg Runtime (s)", "fieldtype": "Float", "width": 110},
	{"fieldname": "p95_runtime_seconds", "label": "p95 Runtime (s)", "fieldtype": "Float", "width": 110},
	{"fieldname": "avg_queue_wait_seconds", "label": "Avg Queue Wait (s)", "fieldtype": "Float", "width": 125},
	{"fieldname": "estimated_gpu_cost", "label": "Estimated GPU Cost", "fieldtype": "Float", "width": 135},
]


def execute(filters=None):
	buckets = defaultdict(_new_bucket)
	for attempt in get_attempt_analytics(filters)[0]:
		bucket = buckets[attempt.comfyui_worker or "Unassigned"]
		bucket["attempts"] += 1
		bucket["completed_attempts"] += attempt.status == "Completed"
		bucket["failed_attempts"] += attempt.status == "Failed"
		bucket["approved_shots"] += attempt.selected_output
		if attempt.runtime_seconds is not None:
			bucket["runtime_seconds"].append(float(attempt.runtime_seconds))
		queue_wait = queue_wait_seconds(attempt)
		if queue_wait is not None:
			bucket["queue_wait_seconds"].append(queue_wait)
		cost = estimated_cost(attempt)
		if cost is not None:
			bucket["costs"].append(cost)

	data = []
	for worker, bucket in sorted(buckets.items()):
		runtimes = bucket["runtime_seconds"]
		queue_waits = bucket["queue_wait_seconds"]
		data.append(
			{
				"comfyui_worker": worker,
				"attempts": bucket["attempts"],
				"completed_attempts": bucket["completed_attempts"],
				"failed_attempts": bucket["failed_attempts"],
				"approved_shots": bucket["approved_shots"],
				"total_runtime_seconds": round(sum(runtimes), 2) if runtimes else None,
				"avg_runtime_seconds": _average(runtimes),
				"p95_runtime_seconds": percentile_95(runtimes),
				"avg_queue_wait_seconds": _average(queue_waits),
				"estimated_gpu_cost": round(sum(bucket["costs"]), 2) if bucket["costs"] else None,
			}
		)
	return COLUMNS, data


def _new_bucket():
	return {
		"attempts": 0,
		"completed_attempts": 0,
		"failed_attempts": 0,
		"approved_shots": 0,
		"runtime_seconds": [],
		"queue_wait_seconds": [],
		"costs": [],
	}


def _average(values):
	return round(sum(values) / len(values), 2) if values else None
