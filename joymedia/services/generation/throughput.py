"""Read-only production throughput report for ``bench execute``."""

from collections import defaultdict
from datetime import timedelta
from statistics import mean, median

import frappe
from frappe.utils import get_datetime, now_datetime


def report(hours=24):
	"""Summarize completed and failed attempts without counting queued work as output."""
	hours = int(hours)
	if not 1 <= hours <= 168:
		raise ValueError("hours must be between 1 and 168")
	since = now_datetime() - timedelta(hours=hours)
	rows = frappe.db.sql(
		"""SELECT a.status, a.failure_class, a.queued_at, a.started_at,
				a.completed_at, a.runtime_seconds, a.timing_json, t.workflow,
				w.output_media_type
			FROM `tabGeneration Attempt` a
			JOIN `tabGeneration Task` t ON t.name = a.generation_task
			JOIN `tabGeneration Workflow` w ON w.name = t.workflow
			WHERE a.creation >= %s AND a.status IN ('Completed', 'Failed')""",
		(since,),
		as_dict=True,
	)
	groups = defaultdict(list)
	for row in rows:
		groups[row.workflow or "Unknown"].append(row)
	groups["all"] = rows
	return {
		"hours": hours,
		"workflows": {key: _summarize(value, hours=hours) for key, value in groups.items()},
	}


def _summarize(rows, *, hours=24):
	queue_waits = []
	runtimes = []
	non_comfy_times = []
	failed_comfy = 0.0
	stages = defaultdict(list)
	for row in rows:
		if row.queued_at and row.started_at:
			queue_waits.append(
				max(0.0, (get_datetime(row.started_at) - get_datetime(row.queued_at)).total_seconds())
			)
		runtime = float(row.runtime_seconds or 0)
		if runtime > 0:
			runtimes.append(runtime)
		try:
			timing = frappe.parse_json(row.timing_json or "{}") or {}
		except (TypeError, ValueError):
			timing = {}
		if isinstance(timing, dict):
			for stage, seconds in timing.items():
				if isinstance(seconds, (int, float)) and seconds >= 0:
					stages[stage].append(float(seconds))
		provider_seconds = timing.get("comfy_execution_seconds") if isinstance(timing, dict) else None
		if runtime > 0 and isinstance(provider_seconds, (int, float)):
			# Includes queueing, polling, transfer and review, not CPU usage.
			non_comfy_times.append(max(0.0, runtime - float(provider_seconds)))
		if row.status == "Failed" and isinstance(provider_seconds, (int, float)):
			failed_comfy += max(0.0, float(provider_seconds))
	completed = sum(row.status == "Completed" for row in rows)
	accepted_clips = sum(row.status == "Completed" and row.output_media_type == "Video" for row in rows)
	failed = sum(row.status == "Failed" for row in rows)
	return {
		"completed_attempts": completed,
		"accepted_video_clips": accepted_clips,
		"accepted_clips_per_hour": round(accepted_clips / hours, 3),
		"failed_attempts": failed,
		"acceptance_rate": round(completed / len(rows), 3) if rows else None,
		"failure_classes": {
			key: sum(row.failure_class == key for row in rows)
			for key in sorted({row.failure_class for row in rows if row.failure_class})
		},
		"observed_queue_wait_p50_seconds": round(median(queue_waits), 1) if queue_waits else None,
		"attempt_runtime_p50_seconds": round(median(runtimes), 1) if runtimes else None,
		"observed_non_comfy_p50_seconds": round(median(non_comfy_times), 1) if non_comfy_times else None,
		"observed_non_comfy_max_seconds": round(max(non_comfy_times), 1) if non_comfy_times else None,
		"known_failed_comfy_seconds": round(failed_comfy, 1),
		"stage_mean_seconds": {key: round(mean(value), 1) for key, value in stages.items()},
	}
