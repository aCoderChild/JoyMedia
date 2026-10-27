"""Persist comparable stage durations on a generation attempt."""

import frappe


def record(attempt, stage, seconds):
	raw = attempt.get("timing_json")
	try:
		values = frappe.parse_json(raw) if isinstance(raw, (str, dict)) else {}
	except (TypeError, ValueError):
		values = {}
	if not isinstance(values, dict):
		values = {}
	if stage not in values:
		values[stage] = round(max(0.0, float(seconds)), 3)
		attempt.timing_json = frappe.as_json(values)


def record_comfy_execution(attempt, history):
	"""Use ComfyUI's own execution events, never an application poll, for GPU time."""
	events = {
		name: details.get("timestamp")
		for name, details in (history.get("status") or {}).get("messages", [])
		if isinstance(details, dict)
	}
	start = events.get("execution_start")
	finish = events.get("execution_success") or events.get("execution_error")
	if isinstance(start, (int, float)) and isinstance(finish, (int, float)) and finish >= start:
		record(attempt, "comfy_execution_seconds", (finish - start) / 1000)
