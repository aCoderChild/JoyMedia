import frappe

from joymedia.services.timeline_editor import _project_fps, _source_max_frames


def execute():
	for clip in frappe.get_all(
		"Timeline Clip",
		filters={"track_type": "Audio", "audio_role": ["!=", "Source"]},
		fields=[
			"name",
			"media_project",
			"source_asset_version",
			"source_in_frame",
			"source_out_frame",
			"initial_source_in_frame",
			"initial_source_out_frame",
		],
	):
		project_fps = _project_fps(clip.media_project)
		legacy_ten_seconds = round(10 * project_fps)
		if (
			int(clip.source_in_frame or 0) != 0
			or int(clip.initial_source_in_frame or 0) != 0
			or int(clip.initial_source_out_frame or 0) != legacy_ten_seconds
			or int(clip.source_out_frame or 0) <= legacy_ten_seconds
		):
			continue

		source_total_frames = _source_max_frames(clip.source_asset_version, project_fps)
		if not source_total_frames or source_total_frames <= legacy_ten_seconds:
			continue

		frappe.db.set_value(
			"Timeline Clip",
			clip.name,
			"initial_source_out_frame",
			int(clip.source_out_frame),
			update_modified=False,
		)
