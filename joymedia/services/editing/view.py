"""Reading a project's timeline: its clips in order, lengths and limits, and the JSON the studio shows."""

import frappe
from frappe import _

from joymedia.services.editing.composer import _get_asset_version_path, _has_audio_stream

MIN_CLIP_SECONDS = 0.25


def _unique_file_url(file_url):
	if not file_url:
		return None
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		return file_url
	return frappe.get_doc("File", file_name).unique_url


def _latest_fully_generated_run(project_name):
	"""Pick the newest run only when every project shot has a selected video.

	Generation results arrive shot-by-shot. Creating the edit timeline after the
	first completed shot would permanently omit later shots, so initialization is
	deferred until the entire shot set is ready.
	"""
	runs = frappe.get_all(
		"Generation Run",
		filters={"media_project": project_name},
		fields=["name", "creation"],
		order_by="creation desc",
	)
	shots = frappe.get_all(
		"Shot",
		filters={"media_project": project_name, "is_removed": 0},
		fields=["name", "selected_output_asset_version"],
	)
	if shots and all(row.selected_output_asset_version for row in shots):
		return runs[0] if runs else None
	return None


def _timeline_clip_rows(project_name):
	return frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name},
		fields=[
			"name",
			"media_project",
			"shot",
			"clip_order",
			"track_type",
			"track_index",
			"linked_video_clip",
			"timeline_start_frame",
			"enabled",
			"source_asset_version",
			"source_in_frame",
			"source_out_frame",
			"initial_source_in_frame",
			"initial_source_out_frame",
			"transition_to_next",
			"transition_frames",
			"audio_role",
			"gain_db",
			"fade_in_frames",
			"fade_out_frames",
			"duck_others",
			"is_outdated",
		],
		order_by="clip_order asc, creation asc",
	)


def _enabled_clips(clips):
	return [clip for clip in clips if clip.enabled]


def _serialize_timeline(project, clips):
	latest_run = _latest_fully_generated_run(project.name)
	enabled_clips = _enabled_clips(clips)
	visible_clips = enabled_clips + [
		clip for clip in clips if not clip.enabled and clip.track_type == "Audio"
	]
	if not enabled_clips:
		return {
			"ready": False,
			"project": project.name,
			"media_project": project.name,
			"latest_generation_run": latest_run.name if latest_run else None,
			"is_outdated": False,
			"clips": [],
			"fps": 0,
			"total_frames": 0,
			"total_seconds": 0,
			"export_status": getattr(project, "export_status", "Idle") or "Idle",
			"export_error": getattr(project, "export_error", None),
			"message": _("Generate every shot before opening the edit timeline."),
		}

	fps = _project_fps(project.name)
	serialized = []
	for index, clip in enumerate(visible_clips):
		length = _clip_length(clip)
		asset = frappe.db.get_value(
			"Asset Version",
			clip.source_asset_version,
			["name", "media_asset", "file", "duration_seconds", "fps"],
			as_dict=True,
		)
		source_total_frames = _source_max_frames(clip.source_asset_version, fps)
		min_duration_frames = _minimum_clip_frames(fps)
		media_asset = (
			frappe.db.get_value(
				"Media Asset", asset.media_asset, ["asset_name", "asset_category"], as_dict=True
			)
			if asset
			else None
		)
		shot_number = frappe.db.get_value("Shot", clip.shot, "shot_number") if clip.shot else None
		start = int(clip.timeline_start_frame or 0)
		end = start + length
		source_has_audio = False
		if (clip.track_type or "Video") == "Video" or clip.audio_role == "Source":
			try:
				source_has_audio = _has_audio_stream(_get_asset_version_path(clip.source_asset_version))
			except Exception:
				source_has_audio = False
		transition = clip.transition_to_next or "Cut"
		transition_frames = int(clip.transition_frames or 0) if transition != "Cut" else 0
		if index == len(visible_clips) - 1:
			transition = "Cut"
			transition_frames = 0
		serialized.append(
			{
				"name": clip.name,
				"clip_order": clip.clip_order,
				"track_type": clip.track_type or "Video",
				"track_index": int(clip.track_index or 0),
				"enabled": bool(clip.enabled),
				"linked_video_clip": clip.linked_video_clip,
				"shot": clip.shot,
				"shot_number": shot_number,
				"source_asset_version": clip.source_asset_version,
				"source_file": _unique_file_url(asset.file) if asset else None,
				"source_has_audio": source_has_audio,
				"source_asset_name": media_asset.asset_name if media_asset else None,
				"source_asset_category": media_asset.asset_category if media_asset else None,
				"source_in_frame": int(clip.source_in_frame),
				"source_out_frame": int(clip.source_out_frame),
				"initial_source_in_frame": int(clip.initial_source_in_frame or clip.source_in_frame),
				"initial_source_out_frame": int(clip.initial_source_out_frame or clip.source_out_frame),
				"source_total_frames": source_total_frames,
				"source_duration_seconds": float(asset.duration_seconds or 0) if asset else 0,
				"source_fps": float(asset.fps or 0) if asset else 0,
				"available_head_frames": max(0, int(clip.source_in_frame)),
				"available_tail_frames": max(
					0, int(source_total_frames or clip.source_out_frame) - int(clip.source_out_frame)
				),
				"min_duration_frames": min_duration_frames,
				"duration_frames": length,
				"duration_seconds": length / fps,
				"timeline_start_frame": start,
				"initial_timeline_start_frame": int(
					clip.initial_timeline_start_frame or clip.timeline_start_frame or 0
				),
				"timeline_end_frame": end,
				"transition_to_next": transition,
				"transition_frames": transition_frames,
				"is_outdated": bool(clip.is_outdated),
				"audio_role": clip.audio_role,
				"gain_db": float(clip.gain_db or 0),
				"fade_in_frames": int(clip.fade_in_frames or 0),
				"fade_out_frames": int(clip.fade_out_frames or 0),
				"duck_others": bool(clip.duck_others),
			}
		)

	final_video = _final_video(project.name)
	render_total_frames = _visual_timeline_end_frame(project.name)
	audio_end_frames = [
		int(clip.timeline_start_frame or 0) + _clip_length(clip)
		for clip in clips
		if clip.track_type == "Audio"
	]
	canvas_total_frames = max([render_total_frames, *audio_end_frames])
	return {
		"ready": bool(serialized),
		"project": project.name,
		"media_project": project.name,
		"latest_generation_run": latest_run.name if latest_run else None,
		"is_outdated": any(item["is_outdated"] for item in serialized),
		"fps": fps,
		"total_frames": render_total_frames,
		"total_seconds": render_total_frames / fps,
		"render_total_frames": render_total_frames,
		"render_total_seconds": render_total_frames / fps,
		"canvas_total_frames": canvas_total_frames,
		"canvas_total_seconds": canvas_total_frames / fps,
		"clips": serialized,
		"final_video": final_video,
		"export_status": getattr(project, "export_status", "Idle") or "Idle",
		"export_error": getattr(project, "export_error", None),
	}


def _final_video(project_name):
	asset_version_name = frappe.db.get_value(
		"Media Project",
		project_name,
		"current_output_asset_version",
	)
	if not asset_version_name:
		return None
	return frappe.db.get_value(
		"Asset Version",
		asset_version_name,
		[
			"name",
			"file",
			"duration_seconds",
			"fps",
		],
		as_dict=True,
	)


def _project_fps(project_name):
	workflow_name = frappe.db.get_value("Media Project", project_name, "workflow")
	if not workflow_name:
		frappe.throw(_("Media Project has no Workflow."))
	fps = float(frappe.db.get_value("Generation Workflow", workflow_name, "output_fps") or 0)
	if fps <= 0:
		frappe.throw(_("Workflow output FPS must be greater than zero."))
	return fps


def _source_max_frames(asset_version_name, project_fps):
	asset = frappe.db.get_value(
		"Asset Version",
		asset_version_name,
		["duration_seconds", "fps"],
		as_dict=True,
	)
	if not asset or not asset.duration_seconds:
		return None
	return max(1, round(float(asset.duration_seconds) * project_fps))


def _visual_timeline_end_frame(project_name):
	clips = frappe.get_all(
		"Timeline Clip",
		filters={
			"media_project": project_name,
			"track_type": "Video",
			"enabled": 1,
		},
		fields=["timeline_start_frame", "source_in_frame", "source_out_frame"],
	)
	return max(
		(
			int(row.timeline_start_frame or 0)
			+ int(row.source_out_frame or 0)
			- int(row.source_in_frame or 0)
			for row in clips
		),
		default=0,
	)


def _minimum_clip_frames(project_fps):
	return max(1, round(MIN_CLIP_SECONDS * project_fps))


def _clip_length(clip):
	return max(0, int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0))
