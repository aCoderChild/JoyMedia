import frappe

from joymedia.services.timeline_editor import _project_fps, _source_max_frames, _visual_timeline_end_frame


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
			"timeline_start_frame",
		],
	):
		project_fps = _project_fps(clip.media_project)
		legacy_ten_seconds = round(10 * project_fps)
		if (
			int(clip.source_in_frame or 0) != 0
			or int(clip.source_out_frame or 0) != legacy_ten_seconds
			or int(clip.initial_source_in_frame or 0) != 0
			or int(clip.initial_source_out_frame or 0) != legacy_ten_seconds
		):
			continue

		source_total_frames = _source_max_frames(clip.source_asset_version, project_fps)
		video_end_frame = _visual_timeline_end_frame(clip.media_project)
		available_frames = video_end_frame - int(clip.timeline_start_frame or 0)
		if not source_total_frames or available_frames <= 0 or source_total_frames <= legacy_ten_seconds:
			continue

		new_source_out = min(source_total_frames, available_frames)
		if new_source_out <= 0:
			continue
		frappe.db.set_value(
			"Timeline Clip",
			clip.name,
			"source_out_frame",
			new_source_out,
			update_modified=False,
		)
