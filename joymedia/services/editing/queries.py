"""Read-only timeline and generated-asset queries shared by finishing services."""

import frappe


def _shot_video_clips(project_name, create=False):
	from joymedia.services.editing.timeline import get_project_timeline

	if create:
		get_project_timeline(project_name)
	return frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video", "enabled": 1, "shot": ["is", "set"]},
		fields=[
			"name",
			"shot",
			"clip_order",
			"timeline_start_frame",
			"source_asset_version",
			"source_in_frame",
			"source_out_frame",
		],
		order_by="timeline_start_frame asc, clip_order asc",
	)


def _latest_version_of(project_name, asset_name):
	asset = frappe.db.get_value(
		"Media Asset", {"asset_name": asset_name, "media_project": project_name}, "name"
	)
	if not asset:
		return None
	return frappe.db.get_value(
		"Asset Version", {"media_asset": asset}, "name", order_by="version_number desc"
	)
