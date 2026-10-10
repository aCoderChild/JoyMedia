"""Persistent lightweight NLE operations for the JoyMedia Studio.

Generation shots describe what should be generated. Timeline Clip documents describe
how generated media is edited afterwards. Keeping those concepts separate lets the
Studio trim, split, reorder and duplicate clips without mutating completed generation
jobs or pretending that a UI-only change affected the final render.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _
from frappe.utils.synchronization import filelock
from joymedia.services.video_composer import _get_asset_version_path, _has_audio_stream
from joymedia.services.render_queue import enqueue_render, is_render_alive


TRANSITIONS = {"Cut", "Dissolve", "Fade"}
MIN_CLIP_SECONDS = 0.25


def _unique_file_url(file_url):
	if not file_url:
		return None
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		return file_url
	return frappe.get_doc("File", file_name).unique_url


def _require_project_read(project):
	if hasattr(project, "_require_read_access"):
		project._require_read_access()
	else:
		project.check_permission("read")


def _require_project_write(project):
	if hasattr(project, "_require_write_access"):
		project._require_write_access()
	else:
		project.check_permission("write")


@frappe.whitelist()
def get_project_timeline(project_name: str, create_if_possible=True):
	project = frappe.get_doc("Media Project", project_name)
	_require_project_read(project)
	if not frappe.db.exists("DocType", "Timeline Clip"):
		return {
			"ready": False,
			"project": project.name,
			"clips": [],
			"fps": 0,
			"total_frames": 0,
			"total_seconds": 0,
			"message": _("The timeline editor is not installed yet. Run the site migration to enable it."),
		}
	create_if_possible = _as_bool(create_if_possible)

	clips = _timeline_clip_rows(project.name)
	if not clips and create_if_possible:
		_require_project_write(project)
		_initialize_timeline(project)
		clips = _timeline_clip_rows(project.name)
	_ensure_source_audio_clips(project, clips)
	clips = _timeline_clip_rows(project.name)

	return _serialize_timeline(project, clips)


@frappe.whitelist()
def reset_project_timeline(project_name: str):
	"""Rebuild the edit timeline from the newest fully generated shot set."""
	project = frappe.get_doc("Media Project", project_name)
	_require_project_write(project)
	for clip_name in frappe.get_all("Timeline Clip", filters={"media_project": project.name}, pluck="name"):
		frappe.delete_doc("Timeline Clip", clip_name, ignore_permissions=True, force=True)
	_initialize_timeline(project)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def reset_timeline_clip(project_name: str, clip_name: str):
	"""Restore one clip to the source range captured when it was created."""
	project, clip = _project_clip(project_name, clip_name)
	_ensure_editable_clip(clip)
	initial_in = int(clip.initial_source_in_frame or 0)
	initial_out = int(clip.initial_source_out_frame or 0)
	if initial_out <= initial_in:
		frappe.throw(_("This clip has no stored baseline range. Reset the timeline to shots to recreate it."))
	clip.source_in_frame = initial_in
	clip.source_out_frame = initial_out
	if clip.track_type == "Audio" and clip.initial_timeline_start_frame is not None:
		clip.timeline_start_frame = int(clip.initial_timeline_start_frame or 0)
	clip.save(ignore_permissions=True)
	_normalize_transitions(project.name)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def trim_timeline_clip(project_name: str, clip_name: str, source_in_frame, source_out_frame):
	project, clip = _project_clip(project_name, clip_name)
	_ensure_editable_clip(clip)
	start = _int_value(source_in_frame, _("Source in frame must be an integer."))
	end = _int_value(source_out_frame, _("Source out frame must be an integer."))
	if start < 0 or end <= start:
		frappe.throw(_("Source out frame must be after source in frame."))

	max_frames = _source_max_frames(clip.source_asset_version, _project_fps(project.name))
	if max_frames and end > max_frames:
		frappe.throw(_("The requested trim exceeds the source clip duration ({0} frames).").format(max_frames))
	min_frames = _minimum_clip_frames(_project_fps(project.name))
	if end - start < min_frames:
		frappe.throw(_("A timeline clip must be at least {0} frames long.").format(min_frames))
	if clip.track_type == "Audio" and start != int(clip.source_in_frame or 0):
		new_timeline_start = int(clip.timeline_start_frame or 0) + start - int(clip.source_in_frame or 0)
		if new_timeline_start < 0:
			frappe.throw(_("Audio trim cannot move the clip before the start of the timeline."))
		clip.timeline_start_frame = new_timeline_start

	clip.source_in_frame = start
	clip.source_out_frame = end
	clip.save(ignore_permissions=True)
	_sync_linked_audio_clip(clip)
	if clip.track_type == "Video":
		_reflow_video_track(project.name)
	_normalize_transitions(project.name)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def reorder_timeline_clip(project_name: str, clip_name: str, target_order):
	project, clip = _project_clip(project_name, clip_name)
	_ensure_editable_clip(clip)
	target = _int_value(target_order, _("Invalid clip position."))
	clips = _timeline_clip_rows(project.name)
	video_clips = [row for row in clips if (row.track_type or "Video") == "Video"]
	if clip.track_type == "Video":
		if target < 1 or target > len(video_clips):
			frappe.throw(_("Invalid video clip position."))
		ordered = [row for row in video_clips if row.name != clip.name]
		ordered.insert(target - 1, next(row for row in video_clips if row.name == clip.name))
		for index, row in enumerate(ordered, start=1):
			frappe.db.set_value("Timeline Clip", row.name, "clip_order", index, update_modified=False)
			linked_audio = _linked_audio_clip(row)
			if linked_audio:
				frappe.db.set_value("Timeline Clip", linked_audio.name, "clip_order", index, update_modified=False)
	else:
		if target < 1 or target > len(clips):
			frappe.throw(_("Invalid clip position."))
		ordered = [row for row in clips if row.name != clip.name]
		ordered.insert(target - 1, next(row for row in clips if row.name == clip.name))
		_set_clip_order(ordered)
	if clip.track_type == "Video":
		_reflow_video_track(project.name)
	_normalize_transitions(project.name)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def split_timeline_clip(project_name: str, clip_name: str, source_split_frame):
	"""Split one clip at an absolute source frame and keep source lineage intact."""
	project, clip = _project_clip(project_name, clip_name)
	_ensure_editable_clip(clip)
	split_frame = _int_value(source_split_frame, _("Split frame must be an integer."))
	if split_frame <= int(clip.source_in_frame) or split_frame >= int(clip.source_out_frame):
		frappe.throw(_("Split frame must be inside the clip source range."))

	clips = _timeline_clip_rows(project.name)
	for row in reversed(clips):
		if row.clip_order > clip.clip_order:
			frappe.db.set_value("Timeline Clip", row.name, "clip_order", row.clip_order + 1, update_modified=False)

	old_out = int(clip.source_out_frame)
	old_transition = clip.transition_to_next or "Cut"
	old_transition_frames = int(clip.transition_frames or 0)
	clip.source_out_frame = split_frame
	clip.transition_to_next = "Cut"
	clip.transition_frames = 0
	clip.save(ignore_permissions=True)
	linked_audio = _linked_audio_clip(clip)
	if clip.track_type == "Video" and linked_audio:
		linked_audio.source_out_frame = split_frame
		linked_audio.save(ignore_permissions=True)

	new_clip = frappe.get_doc(
		{
			"doctype": "Timeline Clip",
			"media_project": clip.media_project,
			"shot": clip.shot,
			"clip_order": clip.clip_order + 1,
			"track_type": clip.track_type,
			"track_index": clip.track_index,
			"timeline_start_frame": int(clip.timeline_start_frame or 0) + split_frame - int(clip.source_in_frame),
			"initial_timeline_start_frame": int(clip.timeline_start_frame or 0) + split_frame - int(clip.source_in_frame),
			"enabled": clip.enabled,
			"source_asset_version": clip.source_asset_version,
			"source_in_frame": split_frame,
			"source_out_frame": old_out,
			"initial_source_in_frame": split_frame,
			"initial_source_out_frame": old_out,
			"transition_to_next": old_transition,
			"transition_frames": old_transition_frames,
			"audio_role": clip.audio_role,
			"gain_db": clip.gain_db,
			"fade_in_frames": clip.fade_in_frames,
			"fade_out_frames": clip.fade_out_frames,
			"duck_others": clip.duck_others,
			"is_outdated": clip.is_outdated,
		}
	).insert(ignore_permissions=True)
	if clip.track_type == "Video" and linked_audio:
		frappe.get_doc(
			{
				"doctype": "Timeline Clip",
				"media_project": clip.media_project,
				"shot": clip.shot,
				"clip_order": new_clip.clip_order,
				"track_type": "Audio",
				"track_index": linked_audio.track_index,
				"linked_video_clip": new_clip.name,
				"timeline_start_frame": new_clip.timeline_start_frame,
				"initial_timeline_start_frame": new_clip.timeline_start_frame,
				"enabled": linked_audio.enabled,
				"source_asset_version": linked_audio.source_asset_version,
				"source_in_frame": split_frame,
				"source_out_frame": old_out,
				"initial_source_in_frame": split_frame,
				"initial_source_out_frame": old_out,
				"audio_role": "Source",
				"transition_to_next": "Cut",
				"transition_frames": 0,
			}
		).insert(ignore_permissions=True)
	_reflow_video_track(project.name)
	_normalize_transitions(project.name)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	result = _serialize_timeline(project, _timeline_clip_rows(project.name))
	result["selected_clip"] = new_clip.name
	return result


@frappe.whitelist()
def duplicate_timeline_clip(project_name: str, clip_name: str):
	project, clip = _project_clip(project_name, clip_name)
	_ensure_editable_clip(clip)
	clips = _timeline_clip_rows(project.name)
	for row in reversed(clips):
		if row.clip_order > clip.clip_order:
			frappe.db.set_value("Timeline Clip", row.name, "clip_order", row.clip_order + 1, update_modified=False)

	new_clip = frappe.get_doc(
		{
			"doctype": "Timeline Clip",
			"media_project": clip.media_project,
			"shot": clip.shot,
			"clip_order": clip.clip_order + 1,
			"track_type": clip.track_type,
			"track_index": clip.track_index,
			"timeline_start_frame": int(clip.timeline_start_frame or 0) + _clip_length(clip),
			"initial_timeline_start_frame": int(clip.timeline_start_frame or 0) + _clip_length(clip),
			"enabled": clip.enabled,
			"source_asset_version": clip.source_asset_version,
			"source_in_frame": clip.source_in_frame,
			"source_out_frame": clip.source_out_frame,
			"initial_source_in_frame": clip.initial_source_in_frame,
			"initial_source_out_frame": clip.initial_source_out_frame,
			"transition_to_next": clip.transition_to_next,
			"transition_frames": clip.transition_frames,
			"audio_role": clip.audio_role,
			"gain_db": clip.gain_db,
			"fade_in_frames": clip.fade_in_frames,
			"fade_out_frames": clip.fade_out_frames,
			"duck_others": clip.duck_others,
			"is_outdated": clip.is_outdated,
		}
	).insert(ignore_permissions=True)
	if clip.track_type == "Video" and _linked_audio_clip(clip):
		linked_audio = _linked_audio_clip(clip)
		frappe.get_doc(
			{
				"doctype": "Timeline Clip",
				"media_project": clip.media_project,
				"shot": clip.shot,
				"clip_order": new_clip.clip_order,
				"track_type": "Audio",
				"track_index": linked_audio.track_index,
				"linked_video_clip": new_clip.name,
				"timeline_start_frame": new_clip.timeline_start_frame,
				"initial_timeline_start_frame": new_clip.timeline_start_frame,
				"enabled": linked_audio.enabled,
				"source_asset_version": linked_audio.source_asset_version,
				"source_in_frame": new_clip.source_in_frame,
				"source_out_frame": new_clip.source_out_frame,
				"initial_source_in_frame": new_clip.initial_source_in_frame,
				"initial_source_out_frame": new_clip.initial_source_out_frame,
				"audio_role": "Source",
				"transition_to_next": "Cut",
				"transition_frames": 0,
			}
		).insert(ignore_permissions=True)
	# A duplicate is an independent edit instance. The original becomes a cut
	# into the duplicate; the duplicate inherits the former outgoing transition.
	clip.transition_to_next = "Cut"
	clip.transition_frames = 0
	clip.save(ignore_permissions=True)
	if clip.track_type == "Video":
		_reflow_video_track(project.name)
	_normalize_transitions(project.name)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	result = _serialize_timeline(project, _timeline_clip_rows(project.name))
	result["selected_clip"] = new_clip.name
	return result


@frappe.whitelist()
def delete_timeline_clip(project_name: str, clip_name: str):
	project, clip = _project_clip(project_name, clip_name)
	if clip.track_type == "Audio" and clip.audio_role == "Source":
		clip.enabled = 0
		clip.save(ignore_permissions=True)
		_invalidate_project_output(project.name)
		frappe.db.commit()
		return _serialize_timeline(project, _timeline_clip_rows(project.name))
	_ensure_editable_clip(clip)
	if clip.track_type == "Video" and clip.shot:
		clip.enabled = 0
		clip.save(ignore_permissions=True)
		linked_audio = _linked_audio_clip(clip)
		if linked_audio:
			linked_audio.enabled = 0
			linked_audio.save(ignore_permissions=True)
	else:
		if clip.track_type == "Video":
			linked_audio = _linked_audio_clip(clip)
			if linked_audio:
				frappe.delete_doc("Timeline Clip", linked_audio.name, ignore_permissions=True, force=True)
		frappe.delete_doc("Timeline Clip", clip.name, ignore_permissions=True, force=True)
	_reflow_video_track(project.name)
	_normalize_transitions(project.name)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def set_source_audio_enabled(project_name: str, video_clip_name: str, enabled):
	project, video_clip = _project_clip(project_name, video_clip_name)
	if video_clip.track_type != "Video":
		frappe.throw(_("Source audio belongs to a video clip."))
	linked_audio = _linked_audio_clip(video_clip)
	if not linked_audio:
		frappe.throw(_("This video clip has no source audio."))
	linked_audio.enabled = 1 if _as_bool(enabled) else 0
	linked_audio.save(ignore_permissions=True)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def set_audio_clip_enabled(project_name: str, clip_name: str, enabled):
	project, clip = _project_clip(project_name, clip_name)
	if clip.track_type != "Audio":
		frappe.throw(_("This is not an audio clip."))
	clip.enabled = 1 if _as_bool(enabled) else 0
	clip.save(ignore_permissions=True)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def restore_timeline_state(project_name: str, state_json):
	project = frappe.get_doc("Media Project", project_name)
	_require_project_write(project)
	try:
		state = json.loads(state_json) if isinstance(state_json, str) else state_json
		rows = state.get("clips", [])
	except (TypeError, ValueError, AttributeError) as exc:
		frappe.throw(_("Invalid timeline history state: {0}").format(str(exc)))

	fields = (
		"shot", "clip_order", "track_type", "track_index", "timeline_start_frame",
		"initial_timeline_start_frame", "enabled",
		"source_asset_version", "source_in_frame", "source_out_frame", "initial_source_in_frame",
		"initial_source_out_frame", "transition_to_next", "transition_frames", "audio_role",
		"gain_db", "fade_in_frames", "fade_out_frames", "duck_others", "is_outdated",
	)
	old_to_new = {}
	for clip_name in frappe.get_all("Timeline Clip", filters={"media_project": project.name}, pluck="name"):
		frappe.delete_doc("Timeline Clip", clip_name, ignore_permissions=True, force=True)

	for row in rows:
		values = {field: row.get(field) for field in fields if field in row}
		values.update({"doctype": "Timeline Clip", "media_project": project.name})
		old_name = row.get("name")
		new_clip = frappe.get_doc(values).insert(ignore_permissions=True)
		if old_name:
			old_to_new[old_name] = new_clip.name

	for row in rows:
		old_link = row.get("linked_video_clip")
		if not old_link or old_link not in old_to_new:
			continue
		frappe.db.set_value(
			"Timeline Clip",
			old_to_new[row.get("name")],
			"linked_video_clip",
			old_to_new[old_link],
			update_modified=False,
		)

	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def fit_audio_clip_to_video(project_name: str, clip_name: str):
	project, clip = _project_clip(project_name, clip_name)
	if clip.track_type != "Audio":
		frappe.throw(_("This is not an audio clip."))
	_ensure_editable_clip(clip)
	fps = _project_fps(project.name)
	source_total_frames = _source_max_frames(clip.source_asset_version, fps)
	if not source_total_frames:
		frappe.throw(_("Unable to determine source audio duration."))

	start_frame = int(clip.timeline_start_frame or 0)
	source_in_frame = int(clip.source_in_frame or 0)
	video_end_frame = _visual_timeline_end_frame(project.name)
	available_frames = video_end_frame - start_frame
	if available_frames <= 0:
		frappe.throw(_("Audio must start before the video ends."))
	if source_in_frame >= source_total_frames:
		frappe.throw(_("The audio source start is beyond the source duration."))

	clip.source_out_frame = min(source_total_frames, source_in_frame + available_frames)
	if clip.source_out_frame <= source_in_frame:
		frappe.throw(_("The audio clip has no usable duration."))
	clip.save(ignore_permissions=True)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def fit_audio_clip_to_full_video(project_name: str, clip_name: str):
	project, clip = _project_clip(project_name, clip_name)
	if clip.track_type != "Audio":
		frappe.throw(_("This is not an audio clip."))
	_ensure_editable_clip(clip)
	fps = _project_fps(project.name)
	source_total_frames = _source_max_frames(clip.source_asset_version, fps)
	if not source_total_frames:
		frappe.throw(_("Unable to determine source audio duration."))

	source_in_frame = int(clip.source_in_frame or 0)
	video_end_frame = _visual_timeline_end_frame(project.name)
	if source_in_frame >= source_total_frames:
		frappe.throw(_("The audio source start is beyond the source duration."))
	usable_frames = min(source_total_frames - source_in_frame, video_end_frame)
	if usable_frames <= 0:
		frappe.throw(_("The video has no usable duration."))

	clip.timeline_start_frame = 0
	clip.source_out_frame = source_in_frame + usable_frames
	clip.save(ignore_permissions=True)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def use_full_audio_source(project_name: str, clip_name: str):
	project, clip = _project_clip(project_name, clip_name)
	if clip.track_type != "Audio":
		frappe.throw(_("This is not an audio clip."))
	_ensure_editable_clip(clip)
	fps = _project_fps(project.name)
	source_total_frames = _source_max_frames(clip.source_asset_version, fps)
	if not source_total_frames:
		frappe.throw(_("Unable to determine source audio duration."))

	clip.timeline_start_frame = 0
	clip.source_in_frame = 0
	clip.source_out_frame = source_total_frames
	clip.save(ignore_permissions=True)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


def _remove_shot_timeline_clips(project_name, shot_name):
	"""Remove the current editorial representation of a Shot and close gaps."""
	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "shot": shot_name},
		fields=["name"],
	)
	for clip in clips:
		if frappe.db.exists("Timeline Clip", clip.name):
			frappe.delete_doc("Timeline Clip", clip.name, ignore_permissions=True, force=True)
	_reflow_video_track(project_name)
	_normalize_transitions(project_name)
	_invalidate_project_output(project_name)


def _reflow_video_track(project_name):
	"""Rebuild the single visual track's order and frame positions without resizing clips."""
	video_clips = frappe.get_all(
		"Timeline Clip",
		filters={
			"media_project": project_name,
			"track_type": "Video",
			"enabled": 1,
		},
		fields=["name", "source_in_frame", "source_out_frame"],
		order_by="clip_order asc, creation asc",
	)
	cursor = 0
	for index, clip in enumerate(video_clips, start=1):
		frappe.db.set_value(
			"Timeline Clip",
			clip.name,
			{
				"clip_order": index,
				"timeline_start_frame": cursor,
			},
			update_modified=False,
		)
		linked_audio = frappe.db.get_value(
			"Timeline Clip",
			{"linked_video_clip": clip.name},
			["name", "clip_order"],
			as_dict=True,
		)
		if linked_audio:
			frappe.db.set_value(
				"Timeline Clip",
				linked_audio.name,
				{
					"clip_order": index,
					"timeline_start_frame": cursor,
				},
				update_modified=False,
			)
		cursor += max(0, int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0))


@frappe.whitelist()
def set_timeline_transition(project_name: str, clip_name: str, transition: str, transition_frames=0):
	project, clip = _project_clip(project_name, clip_name)
	transition = (transition or "Cut").strip()
	if transition not in TRANSITIONS:
		frappe.throw(_("Unsupported transition."))
	frames = _int_value(transition_frames, _("Transition frames must be an integer."))
	if frames < 0:
		frappe.throw(_("Transition frames cannot be negative."))
	if transition == "Cut":
		frames = 0

	clips = _enabled_clips(_timeline_clip_rows(project.name))
	index = next((index for index, row in enumerate(clips) if row.name == clip.name), None)
	if index is None:
		frappe.throw(_("Timeline clip was not found."))
	if index == len(clips) - 1:
		transition = "Cut"
		frames = 0
	elif transition != "Cut":
		current_frames = _clip_length(clip)
		next_frames = _clip_length(clips[index + 1])
		max_transition = max(0, min(current_frames, next_frames) - 1)
		if frames < 1:
			frappe.throw(_("Dissolve and Fade transitions must be at least 1 frame."))
		if frames > max_transition:
			frappe.throw(_("Transition is longer than one of its neighboring clips."))

	clip.transition_to_next = transition
	clip.transition_frames = frames
	clip.save(ignore_permissions=True)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def queue_project_timeline_export(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	_require_project_write(project)
	if getattr(project, "export_status", None) in ("Queued", "Running") and is_render_alive(
		_export_job_id(project.name)
	):
		return {
			"status": project.export_status,
			"export_status": project.export_status,
		}
	from joymedia.services.post_production import _job_id as post_production_job_id

	if getattr(project, "post_production_status", None) in ("Queued", "Running") and is_render_alive(
		post_production_job_id(project.name)
	):
		frappe.throw(_("The film is still being finished. Export once the transitions and soundtrack are added."))
	project.db_set("export_status", "Queued")
	project.db_set("export_error", None)
	enqueue_render(
		"joymedia.services.timeline_editor.run_project_timeline_export",
		_export_job_id(project.name),
		# Studio finishing renders every second of film on the GPU.
		timeout=7200,
		project_name=project.name,
	)
	frappe.db.commit()
	return {
		"status": "Queued",
		"export_status": "Queued",
	}


def _export_job_id(project_name):
	return f"joymedia:export:{project_name}"


def _fail_dead_export(project):
	"""Report an export whose background job died as Failed, so it can be retried."""
	if project.export_status not in ("Queued", "Running") or is_render_alive(_export_job_id(project.name)):
		return
	project.db_set({
		"export_status": "Failed",
		"export_error": _("The export stopped unexpectedly. Please export again."),
		"export_completed_at": frappe.utils.now(),
	})
	frappe.db.commit()


def run_project_timeline_export(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	from joymedia.services.timeline_composer import compose_project_timeline_internal

	try:
		project.db_set("export_status", "Running")
		project.db_set("export_started_at", frappe.utils.now())
		frappe.db.commit()
		result = compose_project_timeline_internal(project.name)
		project.db_set("export_status", "Completed")
		project.db_set("export_completed_at", frappe.utils.now())
		frappe.db.commit()
		return result
	except Exception as exc:
		# A failed write aborts the transaction; record the failure in a fresh one.
		frappe.db.rollback()
		project.db_set("export_status", "Failed")
		from joymedia.services.user_messages import classify_failure, friendly_failure

		# Marketers see a plain message; the technical detail is in the Error Log.
		project.db_set(
			"export_error",
			friendly_failure("Infrastructure")
			if classify_failure(exc) == "Infrastructure"
			else _("The export did not finish. Please export again."),
		)
		project.db_set("export_completed_at", frappe.utils.now())
		frappe.db.commit()
		frappe.log_error(title=f"Timeline export failed for {project_name}")
		raise


@frappe.whitelist()
def get_project_timeline_export_status(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	_require_project_read(project)
	_fail_dead_export(project)
	return {
		"export_status": getattr(project, "export_status", "Idle") or "Idle",
		"export_error": getattr(project, "export_error", None),
		"export_started_at": getattr(project, "export_started_at", None),
		"export_completed_at": getattr(project, "export_completed_at", None),
		"current_output_asset_version": getattr(project, "current_output_asset_version", None),
	}


@frappe.whitelist()
def compose_project_timeline(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	_require_project_write(project)
	from joymedia.services.timeline_composer import compose_project_timeline_internal

	project.db_set("export_status", "Running")
	project.db_set("export_started_at", frappe.utils.now())
	try:
		result = compose_project_timeline_internal(project.name)
		project.db_set("export_status", "Completed")
		project.db_set("export_completed_at", frappe.utils.now())
		frappe.db.commit()
		return result
	except Exception as exc:
		project.db_set("export_status", "Failed")
		project.db_set("export_error", str(exc))
		project.db_set("export_completed_at", frappe.utils.now())
		frappe.db.commit()
		raise


def _initialize_timeline(project):
	_sync_missing_generated_shots_to_timeline(project)


def _create_timeline_clip_pair(project, shot, order, timeline_cursor, fps):
	planned_frames = int(shot.planned_frame_count or round(float(shot.duration_seconds or 0) * fps))
	if planned_frames <= 0:
		return timeline_cursor
	max_frames = _source_max_frames(shot.selected_output_asset_version, fps)
	source_out = min(planned_frames, max_frames) if max_frames else planned_frames
	if source_out <= 0:
		return timeline_cursor
	video_clip = frappe.get_doc(
		{
			"doctype": "Timeline Clip",
			"media_project": project.name,
			"shot": shot.name,
			"clip_order": order,
			"track_type": "Video",
			"track_index": 0,
			"timeline_start_frame": timeline_cursor,
			"initial_timeline_start_frame": timeline_cursor,
			"enabled": 1,
			"source_asset_version": shot.selected_output_asset_version,
			"source_in_frame": 0,
			"source_out_frame": source_out,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": source_out,
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}
	).insert(ignore_permissions=True)
	audio_version = _get_or_create_source_audio_version(shot.selected_output_asset_version)
	if audio_version:
		frappe.get_doc(
			{
				"doctype": "Timeline Clip",
				"media_project": project.name,
				"shot": shot.name,
				"clip_order": order,
				"track_type": "Audio",
				"track_index": 0,
				"linked_video_clip": video_clip.name,
				"timeline_start_frame": timeline_cursor,
				"initial_timeline_start_frame": timeline_cursor,
				"enabled": 1,
				"source_asset_version": audio_version,
				"source_in_frame": 0,
				"source_out_frame": source_out,
				"initial_source_in_frame": 0,
				"initial_source_out_frame": source_out,
				"audio_role": "Source",
				"transition_to_next": "Cut",
				"transition_frames": 0,
			}
		).insert(ignore_permissions=True)
	return timeline_cursor + source_out


def _sync_missing_generated_shots_to_timeline(project):
	fps = _project_fps(project.name)
	existing = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project.name, "track_type": "Video"},
		fields=["shot", "clip_order", "timeline_start_frame", "source_in_frame", "source_out_frame"],
	)
	existing_shots = {row.shot for row in existing if row.shot}
	next_order = max([int(row.clip_order or 0) for row in existing] or [0]) + 1
	timeline_cursor = max(
		[
			int(row.timeline_start_frame or 0)
			+ max(0, int(row.source_out_frame or 0) - int(row.source_in_frame or 0))
			for row in existing
		]
		or [0]
	)
	shots = frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		fields=["name", "shot_number", "planned_frame_count", "duration_seconds", "selected_output_asset_version"],
		order_by="shot_number asc, name asc",
	)
	created = False
	for shot in shots:
		if shot.name in existing_shots or not shot.selected_output_asset_version:
			continue
		timeline_cursor = _create_timeline_clip_pair(project, shot, next_order, timeline_cursor, fps)
		next_order += 1
		created = True
	if created:
		frappe.db.commit()


def _get_or_create_source_audio_version(video_asset_version_name):
	"""Extract and persist the first audio stream for a generated video once."""
	video_version = frappe.get_doc("Asset Version", video_asset_version_name)
	video_asset = frappe.get_doc("Media Asset", video_version.media_asset)
	if video_asset.media_type != "Video":
		frappe.throw(_("Source audio extraction requires a Video Asset Version."))
	existing = frappe.db.get_value(
		"Asset Version",
		{"derived_from": video_version.name},
		["name", "media_asset"],
		as_dict=True,
	)
	if existing and frappe.db.get_value("Media Asset", existing.media_asset, "media_type") == "Audio":
		return existing.name
	existing = None

	with filelock(f"joymedia-source-audio-{video_version.name}"):
		existing = frappe.db.get_value(
			"Asset Version",
			{"derived_from": video_version.name},
			"name",
		)
		if existing and frappe.db.get_value("Media Asset", existing.media_asset, "media_type") == "Audio":
			return existing
		source_path = _get_asset_version_path(video_version.name)
		if not _has_audio_stream(source_path):
			return None
		with tempfile.TemporaryDirectory(prefix=f"joymedia-audio-{video_version.name}-") as temp_dir:
			output_path = Path(temp_dir) / f"{video_version.name}-audio.flac"
			try:
				subprocess.run(
					[
						"ffmpeg", "-v", "error", "-y", "-i", str(source_path),
						"-map", "0:a:0", "-vn", "-c:a", "flac", str(output_path),
					],
					capture_output=True,
					text=True,
					check=True,
				)
			except (OSError, subprocess.CalledProcessError) as exc:
				message = getattr(exc, "stderr", None) or str(exc)
				frappe.throw(_("Unable to extract source audio: {0}").format(message.strip()))
			audio_asset = frappe.get_doc(
				{
					"doctype": "Media Asset",
					"asset_name": f"{video_asset.asset_name} Derived Audio",
					"media_type": "Audio",
					"asset_category": "Derived Audio",
					"asset_scope": "Project Output",
					"media_project": video_asset.media_project,
					"status": "Active",
				}
			).insert(ignore_permissions=True)
			file_doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": output_path.name,
					"content": output_path.read_bytes(),
					"is_private": 1,
					"attached_to_doctype": "Media Asset",
					"attached_to_name": audio_asset.name,
				}
			).insert(ignore_permissions=True)
			audio_version = frappe.get_doc(
				{
					"doctype": "Asset Version",
					"media_asset": audio_asset.name,
					"file": file_doc.file_url,
					"source": "Derived",
					"derived_from": video_version.name,
				}
			).insert(ignore_permissions=True)
			return audio_version.name


def _ensure_source_audio_clips(project, clips):
	"""Backfill linked source-audio clips for timelines created before the split model."""
	video_clips = [clip for clip in clips if (clip.track_type or "Video") == "Video"]
	for video_clip in video_clips:
		linked_audio = _linked_audio_clip(video_clip)
		audio_version = _get_or_create_source_audio_version(video_clip.source_asset_version)
		if linked_audio and not audio_version:
			frappe.delete_doc("Timeline Clip", linked_audio.name, ignore_permissions=True, force=True)
			continue
		if linked_audio:
			if linked_audio.source_asset_version != audio_version:
				linked_audio.source_asset_version = audio_version
				linked_audio.save(ignore_permissions=True)
			continue
		if not audio_version:
			continue
		frappe.get_doc(
			{
				"doctype": "Timeline Clip",
				"media_project": project.name,
				"shot": video_clip.shot,
				"clip_order": video_clip.clip_order,
				"track_type": "Audio",
				"track_index": 0,
				"linked_video_clip": video_clip.name,
				"timeline_start_frame": video_clip.timeline_start_frame,
				"initial_timeline_start_frame": video_clip.timeline_start_frame,
				"enabled": video_clip.enabled,
				"source_asset_version": audio_version,
				"source_in_frame": video_clip.source_in_frame,
				"source_out_frame": video_clip.source_out_frame,
				"initial_source_in_frame": video_clip.initial_source_in_frame,
				"initial_source_out_frame": video_clip.initial_source_out_frame,
				"audio_role": "Source",
				"transition_to_next": "Cut",
				"transition_frames": 0,
			}
		).insert(ignore_permissions=True)
	if video_clips:
		frappe.db.commit()


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
		clip for clip in clips
		if not clip.enabled and clip.track_type == "Audio"
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
			frappe.db.get_value("Media Asset", asset.media_asset, ["asset_name", "asset_category"], as_dict=True)
			if asset
			else None
		)
		shot_number = (
			frappe.db.get_value("Shot", clip.shot, "shot_number")
			if clip.shot
			else None
		)
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
				"available_tail_frames": max(0, int(source_total_frames or clip.source_out_frame) - int(clip.source_out_frame)),
				"min_duration_frames": min_duration_frames,
				"duration_frames": length,
				"duration_seconds": length / fps,
				"timeline_start_frame": start,
				"initial_timeline_start_frame": int(clip.initial_timeline_start_frame or clip.timeline_start_frame or 0),
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


def _invalidate_project_output(project_name):
	frappe.db.set_value(
		"Media Project",
		project_name,
		{
			"current_output_asset_version": None,
			"export_status": "Idle",
			"export_error": None,
		},
		update_modified=False,
	)


def sync_timeline_source_for_shot(shot_name):
	"""Mark editorial clips stale when a Shot receives a new output.

		Generation must not replace an existing editorial source automatically.
	"""
	shot = frappe.get_doc("Shot", shot_name)
	new_asset_version = shot.selected_output_asset_version
	if not new_asset_version:
		return
	project_name = shot.media_project
	clips = frappe.get_all(
		"Timeline Clip",
		filters={
			"media_project": project_name,
			"shot": shot.name,
		},
		fields=["name", "source_in_frame", "source_out_frame"],
	)
	if not clips:
		_initialize_timeline(frappe.get_doc("Media Project", project_name))
		return
	for clip_data in clips:
		frappe.db.sql(
			"UPDATE `tabTimeline Clip` SET `is_outdated` = 1 WHERE `name` = %s",
			clip_data.name,
		)

	_invalidate_project_output(project_name)
	frappe.db.commit()


@frappe.whitelist()
def update_timeline_source_for_shot(project_name: str, shot_name: str):
	"""Explicitly replace editorial clips with the Shot's current output."""
	project = frappe.get_doc("Media Project", project_name)
	_require_project_write(project)
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	if not shot.selected_output_asset_version:
		frappe.throw(_("Shot has no selected output Asset Version."))
	for clip_name in frappe.get_all(
		"Timeline Clip", filters={"media_project": project.name, "shot": shot.name}, pluck="name"
	):
		clip = frappe.get_doc("Timeline Clip", clip_name)
		if clip.track_type == "Video":
			max_frames = _source_max_frames(shot.selected_output_asset_version, _project_fps(project.name))
			if max_frames and clip.source_out_frame > max_frames:
				clip.source_out_frame = max_frames
				if clip.source_out_frame - clip.source_in_frame < _minimum_clip_frames(_project_fps(project.name)):
					clip.source_in_frame = max(0, max_frames - _minimum_clip_frames(_project_fps(project.name)))
			clip.source_asset_version = shot.selected_output_asset_version
			clip.initial_source_out_frame = min(
				clip.initial_source_out_frame or clip.source_out_frame, clip.source_out_frame
			)
			clip.is_outdated = 0
			clip.save(ignore_permissions=True)
			_sync_linked_audio_clip(clip)
	_normalize_transitions(project.name)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def move_timeline_clip(project_name: str, clip_name: str, timeline_start_frame, track_type=None, track_index=None):
	project, clip = _project_clip(project_name, clip_name)
	_ensure_editable_clip(clip)
	start = _int_value(timeline_start_frame, _("Timeline start frame must be an integer."))
	if start < 0:
		frappe.throw(_("Timeline start frame cannot be negative."))
	if track_type is not None and track_type not in ("Video", "Audio"):
		frappe.throw(_("Timeline clip track type must be Video or Audio."))
	clip.timeline_start_frame = start
	if track_type is not None:
		clip.track_type = track_type
	if track_index is not None:
		clip.track_index = _int_value(track_index, _("Track index must be an integer."))
		if clip.track_index < 0:
			frappe.throw(_("Track index cannot be negative."))
	clip.save(ignore_permissions=True)
	if clip.track_type == "Video":
		_sync_linked_audio_clip(clip)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def update_timeline_clip_audio(
	project_name: str,
	clip_name: str,
	gain_db=None,
	fade_in_frames=None,
	fade_out_frames=None,
	duck_others=None,
	audio_role=None,
):
	project, clip = _project_clip(project_name, clip_name)
	if gain_db is not None:
		try:
			clip.gain_db = float(gain_db)
		except (TypeError, ValueError):
			frappe.throw(_("Gain must be a valid number."))
	if fade_in_frames is not None:
		clip.fade_in_frames = max(0, _int_value(fade_in_frames, _("Fade in frames must be an integer.")))
	if fade_out_frames is not None:
		clip.fade_out_frames = max(0, _int_value(fade_out_frames, _("Fade out frames must be an integer.")))
	if duck_others is not None:
		clip.duck_others = 1 if _as_bool(duck_others) else 0
	if audio_role is not None and clip.audio_role != "Source":
		role = str(audio_role).strip()
		if role in ("BGM", "Voiceover", "SFX"):
			clip.audio_role = role
	clip.save(ignore_permissions=True)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def add_timeline_audio_clip(
	project_name: str,
	asset_version_name: str,
	timeline_start_frame=0,
	audio_role="BGM",
):
	project = frappe.get_doc("Media Project", project_name)
	_require_project_write(project)
	asset_version = frappe.get_doc("Asset Version", asset_version_name)
	media_asset = frappe.get_doc("Media Asset", asset_version.media_asset)
	if media_asset.media_type != "Audio":
		frappe.throw(_("Only Audio assets can be added to an audio track."))
	fps = _project_fps(project.name)
	start_frame = max(0, _int_value(timeline_start_frame, _("Start frame must be an integer.")))
	source_total_frames = _source_max_frames(asset_version.name, fps)
	if not source_total_frames:
		frappe.throw(_("Unable to determine the audio asset duration."))
	source_out = source_total_frames

	existing_audio_indexes = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project.name, "track_type": "Audio"},
		pluck="track_index",
	)
	next_audio_track_index = max([int(index or 0) for index in existing_audio_indexes] or [0]) + 1
	order = (frappe.db.count("Timeline Clip", {"media_project": project.name}) or 0) + 1
	new_clip = frappe.get_doc(
		{
			"doctype": "Timeline Clip",
			"media_project": project.name,
			"clip_order": order,
			"track_type": "Audio",
			"track_index": next_audio_track_index,
			"timeline_start_frame": start_frame,
			"initial_timeline_start_frame": start_frame,
			"enabled": 1,
			"source_asset_version": asset_version.name,
			"source_in_frame": 0,
			"source_out_frame": source_out,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": source_out,
			"audio_role": audio_role or "BGM",
			"gain_db": 0.0,
			"fade_in_frames": 0,
			"fade_out_frames": 0,
			"duck_others": 0,
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}
	).insert(ignore_permissions=True)
	_invalidate_project_output(project.name)
	frappe.db.commit()
	result = _serialize_timeline(project, _timeline_clip_rows(project.name))
	result["selected_clip"] = new_clip.name
	return result



def _project_clip(project_name, clip_name):
	project = frappe.get_doc("Media Project", project_name)
	_require_project_write(project)
	clip = frappe.get_doc("Timeline Clip", clip_name)
	if clip.media_project != project.name:
		frappe.throw(_("Timeline clip does not belong to this project."))
	return project, clip


def _linked_audio_clip(video_clip):
	if video_clip.track_type != "Video":
		return None
	linked_name = video_clip.linked_video_clip or frappe.db.get_value(
		"Timeline Clip",
		{"linked_video_clip": video_clip.name, "track_type": "Audio"},
		"name",
	)
	return frappe.get_doc("Timeline Clip", linked_name) if linked_name else None


def _ensure_editable_clip(clip):
	if clip.track_type == "Audio" and clip.audio_role == "Source":
		frappe.throw(_("Source audio follows its linked video clip."))


def _sync_linked_audio_clip(video_clip):
	linked_audio = _linked_audio_clip(video_clip)
	if not linked_audio:
		return
	audio_version = _get_or_create_source_audio_version(video_clip.source_asset_version)
	if not audio_version:
		frappe.delete_doc("Timeline Clip", linked_audio.name, ignore_permissions=True, force=True)
		return
	linked_audio.timeline_start_frame = video_clip.timeline_start_frame
	linked_audio.source_in_frame = video_clip.source_in_frame
	linked_audio.source_out_frame = video_clip.source_out_frame
	linked_audio.initial_source_in_frame = video_clip.initial_source_in_frame
	linked_audio.initial_source_out_frame = video_clip.initial_source_out_frame
	linked_audio.source_asset_version = audio_version
	linked_audio.save(ignore_permissions=True)


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


def _set_clip_order(clips):
	for index, row in enumerate(clips, start=1):
		frappe.db.set_value("Timeline Clip", row.name, "clip_order", index, update_modified=False)


def _normalize_transitions(project_name):
	clips = [
		clip for clip in _enabled_clips(_timeline_clip_rows(project_name))
		if (clip.track_type or "Video") == "Video"
	]
	for index, clip in enumerate(clips):
		transition = clip.transition_to_next or "Cut"
		frames = int(clip.transition_frames or 0)
		if index == len(clips) - 1 or transition not in TRANSITIONS:
			transition = "Cut"
			frames = 0
		elif transition != "Cut":
			max_frames = max(0, min(_clip_length(clip), _clip_length(clips[index + 1])) - 1)
			frames = min(frames, max_frames)
			if frames < 1:
				transition = "Cut"
				frames = 0
		else:
			frames = 0
		frappe.db.set_value(
			"Timeline Clip",
			clip.name,
			{"transition_to_next": transition, "transition_frames": frames},
			update_modified=False,
		)


def _int_value(value, message):
	try:
		return int(value)
	except (TypeError, ValueError):
		frappe.throw(message)


def _as_bool(value):
	if isinstance(value, str):
		return value.lower() not in {"0", "false", "no", "off", ""}
	return bool(value)
