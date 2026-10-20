#!/usr/bin/env python3
"""Read-only evidence recorder for opt-in real UI rendering tests.

Run from a Bench using its Python environment. Writes only the supplied evidence
folder; it never submits, retries, cancels or updates an application job.
"""

import argparse
import datetime
import json
import time
from pathlib import Path

import frappe
import requests


def collect(project, base_url, directory, seen):
	frappe.db.rollback()  # each sample sees current committed worker state
	runs = frappe.get_all(
		"Generation Run",
		filters={"media_project": project},
		fields=["name", "status", "creation", "completed_at", "error_summary"],
	)
	tasks = frappe.get_all(
		"Generation Task",
		filters={"generation_run": ["in", [r.name for r in runs] or [""]]},
		fields=["name", "generation_run", "shot", "status", "segment_frame_count", "error_summary"],
	)
	attempts = frappe.get_all(
		"Generation Attempt",
		filters={"generation_task": ["in", [t.name for t in tasks] or [""]]},
		fields=[
			"name",
			"generation_task",
			"status",
			"external_job_id",
			"creation",
			"queued_at",
			"started_at",
			"completed_at",
			"error_summary",
			"seed",
		],
	)
	snapshot = {
		"at": datetime.datetime.now(datetime.UTC).isoformat(),
		"runs": runs,
		"tasks": tasks,
		"attempts": attempts,
	}
	try:
		response = requests.get(base_url.rstrip("/") + "/queue", timeout=10)
		response.raise_for_status()
		snapshot["comfy_queue"] = {
			key: [{"number": item[0], "prompt": item[1]} for item in items]
			for key, items in response.json().items()
		}
		for attempt in attempts:
			if (
				not attempt.external_job_id
				or attempt.external_job_id in seen
				or attempt.status not in {"Completed", "Failed", "Cancelled"}
			):
				continue
			response = requests.get(base_url.rstrip("/") + "/history/" + attempt.external_job_id, timeout=15)
			response.raise_for_status()
			history = response.json()
			if history:
				(directory / f"comfy-{attempt.name}.json").write_text(json.dumps(history, default=str))
				seen.add(attempt.external_job_id)
	except (requests.RequestException, ValueError) as exc:
		snapshot["monitor_error"] = str(exc)
	return snapshot


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("site")
	parser.add_argument("project")
	parser.add_argument("output", type=Path)
	parser.add_argument("--comfy-base-url", default="http://127.0.0.1:8188")
	parser.add_argument("--seconds", type=int, default=2400)
	args = parser.parse_args()
	if not 1 <= args.seconds <= 7200:
		parser.error("seconds must be between 1 and 7200")
	frappe.init(site=args.site, sites_path="sites")
	frappe.connect()
	try:
		if not frappe.db.exists("Media Project", args.project):
			parser.error("project does not exist")
		args.output.mkdir(parents=True, exist_ok=True)
		seen, deadline = set(), time.monotonic() + args.seconds
		while time.monotonic() < deadline:
			snapshot = collect(args.project, args.comfy_base_url, args.output, seen)
			with (args.output / "backend-snapshots.jsonl").open("a") as stream:
				stream.write(json.dumps(snapshot, default=str) + "\n")
			target = args.output / "latest-backend.json"
			temporary = target.with_suffix(".tmp")
			temporary.write_text(json.dumps(snapshot, indent=2, default=str))
			temporary.replace(target)
			time.sleep(min(5, max(0, deadline - time.monotonic())))
	finally:
		frappe.destroy()


if __name__ == "__main__":
	main()
