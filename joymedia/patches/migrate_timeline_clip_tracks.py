"""Backfill persisted Timeline Clip placement and stale state."""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Timeline Clip"):
		return
	projects = frappe.db.sql(
		"SELECT DISTINCT media_project FROM `tabTimeline Clip` WHERE media_project IS NOT NULL",
		pluck=True,
	)
	for project_name in projects:
		cursor = 0
		rows = frappe.get_all(
			"Timeline Clip",
			filters={"media_project": project_name},
			fields=["name", "clip_order", "shot", "source_asset_version", "source_in_frame", "source_out_frame"],
			order_by="clip_order asc, creation asc",
		)
		for row in rows:
			selected = frappe.db.get_value("Shot", row.shot, "selected_output_asset_version") if row.shot else None
			frappe.db.set_value(
				"Timeline Clip",
				row.name,
				{
					"track_type": "Video",
					"track_index": 0,
					"timeline_start_frame": cursor,
					"is_outdated": int(bool(selected and selected != row.source_asset_version)),
				},
				update_modified=False,
			)
			cursor += max(0, int(row.source_out_frame or 0) - int(row.source_in_frame or 0))
