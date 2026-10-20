#!/usr/bin/env python3
"""Create an isolated copy for real UI rendering; never copy generation jobs.

Creates an Experiment edit inside the original project family, sharing immutable
reference and starting video files. Clears first-frame approvals so the live test
actually redraws through the UI. The working client edit stays selected. This is a local Bench test utility, not a public application endpoint.
"""

import argparse
import datetime
import json
from pathlib import Path

import frappe


def clone(source, title):
	from joymedia.services.project.versions import create_edit

	source._require_write_access()
	result = create_edit(source.name, title[:100], kind="Experiment", make_working=False)
	project = frappe.get_doc("Media Project", result["edit"])
	project.db_set("soundtrack_mode", "Full soundtrack", update_modified=False)
	for name in frappe.get_all("Shot", filters={"media_project": project.name}, pluck="name"):
		frappe.db.set_value(
			"Shot",
			name,
			{"keyframe_artifact": None, "keyframe_status": None, "keyframe_signature": None},
			update_modified=False,
		)

	old = {
		row.shot_number: row
		for row in frappe.get_all(
			"Shot", filters={"media_project": source.name, "is_removed": 0}, fields=["name", "shot_number"]
		)
	}
	shots = [
		{
			"source": old[row.shot_number].name,
			"name": row.name,
			"number": row.shot_number,
			"initial_take": row.selected_output_asset_version,
			"duration": row.duration_seconds,
		}
		for row in frappe.get_all(
			"Shot",
			filters={"media_project": project.name, "is_removed": 0},
			fields=["name", "shot_number", "selected_output_asset_version", "duration_seconds"],
			order_by="shot_number",
		)
	]
	return {
		"project": project.name,
		"source_project": source.name,
		"shots": shots,
		"initial_source_output": source.current_output_asset_version,
		"account": frappe.session.user,
		"created_at": datetime.datetime.now(datetime.UTC).isoformat(),
		"soundtrack_mode": project.soundtrack_mode,
	}


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("site")
	parser.add_argument("source_project")
	parser.add_argument("output", type=Path)
	args = parser.parse_args()
	frappe.init(site=args.site, sites_path="sites")
	frappe.connect()
	try:
		source = frappe.get_doc("Media Project", args.source_project)
		frappe.set_user(source.owner)
		result = clone(
			source, "Live UI render stress " + datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
		)
		frappe.db.commit()
		args.output.mkdir(parents=True, exist_ok=True)
		(args.output / "fixture.json").write_text(json.dumps(result, indent=2))
		print(result["project"])
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()


if __name__ == "__main__":
	main()
