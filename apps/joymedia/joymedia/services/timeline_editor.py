"""Persistent lightweight NLE operations for the JoyMedia Studio.

Generation shots describe what should be generated. Timeline Clip documents describe
how generated media is edited afterwards. Keeping those concepts separate lets the
Studio trim, split, reorder and duplicate clips without mutating completed generation
jobs or pretending that a UI-only change affected the final render.
"""

import frappe
from frappe import _


TRANSITIONS = {"Cut", "Dissolve", "Fade"}
MIN_CLIP_SECONDS = 0.25


@frappe.whitelist()
def get_project_timeline(project_name: str, create_if_possible=True):
	project = frappe.get_doc("Media Project", project_name)
	project.check_permission("read")
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
		project.check_permission("write")
		_initialize_timeline(project)
		clips = _timeline_clip_rows(project.name)

	return _serialize_timeline(project, clips)


@frappe.whitelist()
def reset_project_timeline(project_name: str):
	"""Rebuild the edit timeline from the newest fully generated shot set."""
	project = frappe.get_doc("Media Project", project_name)
	project.check_permission("write")
	for clip_name in frappe.get_all("Timeline Clip", filters={"media_project": project.name}, pluck="name"):
		frappe.delete_doc("Timeline Clip", clip_name, ignore_permissions=True, force=True)
	_initialize_timeline(project)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def reset_timeline_clip(project_name: str, clip_name: str):
	"""Restore one clip to the source range captured when it was created."""
	project, clip = _project_clip(project_name, clip_name)
	initial_in = int(clip.initial_source_in_frame or 0)
	initial_out = int(clip.initial_source_out_frame or 0)
	if initial_out <= initial_in:
		frappe.throw(_("This clip has no stored baseline range. Reset the timeline to shots to recreate it."))
	clip.source_in_frame = initial_in
	clip.source_out_frame = initial_out
	clip.save(ignore_permissions=True)
	_normalize_transitions(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def trim_timeline_clip(project_name: str, clip_name: str, source_in_frame, source_out_frame):
	project, clip = _project_clip(project_name, clip_name)
	start = _int_value(source_in_frame, _("Source in frame must be an integer."))
	end = _int_value(source_out_frame, _("Source out frame must be an integer."))
	if start < 0 or end <= start:
		frappe.throw(_("Source out frame must be after source in frame."))

	max_frames = _source_max_frames(clip.source_asset_version, _project_fps(clip.media_specification))
	if max_frames and end > max_frames:
		frappe.throw(_("The requested trim exceeds the source clip duration ({0} frames).").format(max_frames))
	min_frames = _minimum_clip_frames(_project_fps(clip.media_specification))
	if end - start < min_frames:
		frappe.throw(_("A timeline clip must be at least {0} frames long.").format(min_frames))

	clip.source_in_frame = start
	clip.source_out_frame = end
	clip.save(ignore_permissions=True)
	_normalize_transitions(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def reorder_timeline_clip(project_name: str, clip_name: str, target_order):
	project, clip = _project_clip(project_name, clip_name)
	target = _int_value(target_order, _("Invalid clip position."))
	clips = _timeline_clip_rows(project.name)
	if target < 1 or target > len(clips):
		frappe.throw(_("Invalid clip position."))

	ordered = [row for row in clips if row.name != clip.name]
	ordered.insert(target - 1, next(row for row in clips if row.name == clip.name))
	_set_clip_order(ordered)
	_normalize_transitions(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def split_timeline_clip(project_name: str, clip_name: str, source_split_frame):
	"""Split one clip at an absolute source frame and keep source lineage intact."""
	project, clip = _project_clip(project_name, clip_name)
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

	new_clip = frappe.get_doc(
		{
			"doctype": "Timeline Clip",
			"media_project": clip.media_project,
			"media_specification": clip.media_specification,
			"shot_specification": clip.shot_specification,
			"clip_order": clip.clip_order + 1,
			"enabled": clip.enabled,
			"source_asset_version": clip.source_asset_version,
			"source_in_frame": split_frame,
			"source_out_frame": old_out,
			"initial_source_in_frame": split_frame,
			"initial_source_out_frame": old_out,
			"transition_to_next": old_transition,
			"transition_frames": old_transition_frames,
		}
	).insert(ignore_permissions=True)
	_normalize_transitions(project.name)
	frappe.db.commit()
	result = _serialize_timeline(project, _timeline_clip_rows(project.name))
	result["selected_clip"] = new_clip.name
	return result


@frappe.whitelist()
def duplicate_timeline_clip(project_name: str, clip_name: str):
	project, clip = _project_clip(project_name, clip_name)
	clips = _timeline_clip_rows(project.name)
	for row in reversed(clips):
		if row.clip_order > clip.clip_order:
			frappe.db.set_value("Timeline Clip", row.name, "clip_order", row.clip_order + 1, update_modified=False)

	new_clip = frappe.get_doc(
		{
			"doctype": "Timeline Clip",
			"media_project": clip.media_project,
			"media_specification": clip.media_specification,
			"shot_specification": clip.shot_specification,
			"clip_order": clip.clip_order + 1,
			"enabled": clip.enabled,
			"source_asset_version": clip.source_asset_version,
			"source_in_frame": clip.source_in_frame,
			"source_out_frame": clip.source_out_frame,
			"initial_source_in_frame": clip.initial_source_in_frame,
			"initial_source_out_frame": clip.initial_source_out_frame,
			"transition_to_next": clip.transition_to_next,
			"transition_frames": clip.transition_frames,
		}
	).insert(ignore_permissions=True)
	# A duplicate is an independent edit instance. The original becomes a cut
	# into the duplicate; the duplicate inherits the former outgoing transition.
	clip.transition_to_next = "Cut"
	clip.transition_frames = 0
	clip.save(ignore_permissions=True)
	_normalize_transitions(project.name)
	frappe.db.commit()
	result = _serialize_timeline(project, _timeline_clip_rows(project.name))
	result["selected_clip"] = new_clip.name
	return result


@frappe.whitelist()
def delete_timeline_clip(project_name: str, clip_name: str):
	project, clip = _project_clip(project_name, clip_name)
	frappe.delete_doc("Timeline Clip", clip.name, ignore_permissions=True, force=True)
	_set_clip_order(_timeline_clip_rows(project.name))
	_normalize_transitions(project.name)
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


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
	frappe.db.commit()
	return _serialize_timeline(project, _timeline_clip_rows(project.name))


@frappe.whitelist()
def compose_project_timeline(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	project.check_permission("write")
	from joymedia.services.timeline_composer import compose_project_timeline_internal

	result = compose_project_timeline_internal(project.name)
	frappe.db.commit()
	return result


def _initialize_timeline(project):
	if frappe.db.exists("Timeline Clip", {"media_project": project.name}):
		return

	media_specification = _latest_fully_generated_specification(project.name)
	if not media_specification:
		return
	fps = _project_fps(media_specification.name)
	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_specification.name},
		fields=[
			"name",
			"shot_number",
			"planned_frame_count",
			"duration_seconds",
			"selected_output_asset_version",
		],
		order_by="shot_number asc, name asc",
	)
	for order, shot in enumerate(shots, start=1):
		planned_frames = int(shot.planned_frame_count or round(float(shot.duration_seconds or 0) * fps))
		if planned_frames <= 0:
			continue
		max_frames = _source_max_frames(shot.selected_output_asset_version, fps)
		source_out = min(planned_frames, max_frames) if max_frames else planned_frames
		if source_out <= 0:
			continue
		frappe.get_doc(
			{
				"doctype": "Timeline Clip",
				"media_project": project.name,
				"media_specification": media_specification.name,
				"shot_specification": shot.name,
				"clip_order": order,
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
	frappe.db.commit()


def _latest_fully_generated_specification(project_name):
	"""Pick the newest spec only when every storyboard shot has a selected video.

	Generation results arrive shot-by-shot. Creating the edit timeline after the
	first completed shot would permanently omit later shots, so initialization is
	deferred until the entire shot set is ready.
	"""
	specifications = frappe.get_all(
		"Media Specification",
		filters={"media_project": project_name},
		fields=["name", "version_number"],
		order_by="version_number desc, creation desc",
	)
	for specification in specifications:
		shots = frappe.get_all(
			"Shot Specification",
			filters={"media_specification": specification.name},
			fields=["name", "selected_output_asset_version"],
		)
		if shots and all(row.selected_output_asset_version for row in shots):
			return frappe.get_doc("Media Specification", specification.name)
	return None


def _timeline_clip_rows(project_name):
	return frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name},
		fields=[
			"name",
			"media_project",
			"media_specification",
			"shot_specification",
			"clip_order",
			"enabled",
			"source_asset_version",
			"source_in_frame",
			"source_out_frame",
			"initial_source_in_frame",
			"initial_source_out_frame",
			"transition_to_next",
			"transition_frames",
		],
		order_by="clip_order asc, creation asc",
	)


def _enabled_clips(clips):
	return [clip for clip in clips if clip.enabled]


def _serialize_timeline(project, clips):
	enabled_clips = _enabled_clips(clips)
	if not enabled_clips:
		return {
			"ready": False,
			"project": project.name,
			"clips": [],
			"fps": 0,
			"total_frames": 0,
			"total_seconds": 0,
			"message": _("Generate every shot before opening the edit timeline."),
		}

	specification_name = enabled_clips[0].media_specification
	fps = _project_fps(specification_name)
	cursor = 0
	serialized = []
	for index, clip in enumerate(enabled_clips):
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
			frappe.db.get_value("Shot Specification", clip.shot_specification, "shot_number")
			if clip.shot_specification
			else None
		)
		start = cursor
		end = start + length
		transition = clip.transition_to_next or "Cut"
		transition_frames = int(clip.transition_frames or 0) if transition != "Cut" else 0
		if index == len(enabled_clips) - 1:
			transition = "Cut"
			transition_frames = 0
		serialized.append(
			{
				"name": clip.name,
				"clip_order": clip.clip_order,
				"shot_specification": clip.shot_specification,
				"shot_number": shot_number,
				"source_asset_version": clip.source_asset_version,
				"source_file": asset.file if asset else None,
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
				"timeline_end_frame": end,
				"transition_to_next": transition,
				"transition_frames": transition_frames,
			}
		)
		cursor = end - transition_frames

	final_video = _final_video(specification_name)
	return {
		"ready": bool(serialized),
		"project": project.name,
		"media_specification": specification_name,
		"fps": fps,
		"total_frames": max(0, cursor),
		"total_seconds": max(0, cursor) / fps,
		"clips": serialized,
		"final_video": final_video,
	}


def _final_video(specification_name):
	asset_version_name = frappe.db.get_value("Media Specification", specification_name, "final_asset_version")
	if not asset_version_name:
		return None
	return frappe.db.get_value(
		"Asset Version",
		asset_version_name,
		["name", "file", "duration_seconds", "fps"],
		as_dict=True,
	)


def _project_clip(project_name, clip_name):
	project = frappe.get_doc("Media Project", project_name)
	project.check_permission("write")
	clip = frappe.get_doc("Timeline Clip", clip_name)
	if clip.media_project != project.name:
		frappe.throw(_("Timeline clip does not belong to this project."))
	return project, clip


def _project_fps(media_specification_name):
	workflow_name = frappe.db.get_value("Media Specification", media_specification_name, "workflow")
	if not workflow_name:
		frappe.throw(_("Media Specification has no Workflow."))
	fps = float(frappe.db.get_value("Workflow", workflow_name, "output_fps") or 0)
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


def _minimum_clip_frames(project_fps):
	return max(1, round(MIN_CLIP_SECONDS * project_fps))


def _clip_length(clip):
	return max(0, int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0))


def _set_clip_order(clips):
	for index, row in enumerate(clips, start=1):
		frappe.db.set_value("Timeline Clip", row.name, "clip_order", index, update_modified=False)


def _normalize_transitions(project_name):
	clips = _enabled_clips(_timeline_clip_rows(project_name))
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
