"""Move legacy Audio Cue rows into Timeline Clip and remove the old child DocType."""

import frappe


def execute():
	if frappe.db.exists("DocType", "Timeline Clip") and frappe.db.exists("DocType", "Audio Cue"):
		rows = frappe.db.sql(
			"""
			SELECT name, parent, asset_version, role, start_seconds, end_seconds,
				gain_db, fade_in_seconds, fade_out_seconds, duck_others
			FROM `tabAudio Cue`
			WHERE parenttype = 'Media Project'
			ORDER BY parent, idx, creation
			""",
			as_dict=True,
		)
		for row in rows:
			workflow = frappe.db.get_value("Media Project", row.parent, "workflow")
			fps = frappe.db.get_value("Generation Workflow", workflow, "output_fps") if workflow else None
			if not fps or not row.asset_version:
				continue
			start_frame = max(0, round(float(row.start_seconds or 0) * float(fps)))
			asset_duration = frappe.db.get_value("Asset Version", row.asset_version, "duration_seconds") or 0
			end_seconds = row.end_seconds if row.end_seconds not in (None, "") else asset_duration
			end_frame = max(1, round(float(end_seconds or 0) * float(fps)))
			if end_frame <= 0:
				continue
			if frappe.db.exists(
				"Timeline Clip",
				{
					"media_project": row.parent,
					"track_type": "Audio",
					"source_asset_version": row.asset_version,
					"timeline_start_frame": start_frame,
				},
			):
				continue
			clip_order = (
				frappe.db.count("Timeline Clip", {"media_project": row.parent}) + 1
			)
			frappe.get_doc(
				{
					"doctype": "Timeline Clip",
					"media_project": row.parent,
					"clip_order": clip_order,
					"track_type": "Audio",
					"track_index": 0,
					"timeline_start_frame": start_frame,
					"enabled": 1,
					"source_asset_version": row.asset_version,
					"source_in_frame": 0,
					"source_out_frame": end_frame,
					"initial_source_in_frame": 0,
					"initial_source_out_frame": end_frame,
					"audio_role": row.role or "SFX",
					"gain_db": row.gain_db or 0,
					"fade_in_frames": round(float(row.fade_in_seconds or 0) * float(fps)),
					"fade_out_frames": round(float(row.fade_out_seconds or 0) * float(fps)),
					"duck_others": row.duck_others or 0,
					"transition_to_next": "Cut",
					"transition_frames": 0,
				}
			).insert(ignore_permissions=True)

	if frappe.db.exists("DocType", "Audio Cue"):
		frappe.delete_doc("DocType", "Audio Cue", force=True, ignore_permissions=True)
