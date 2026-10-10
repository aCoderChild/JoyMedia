# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt


"""HTTP endpoints for storyboard revision, shots, scenes and reordering."""

import frappe
from frappe import _
from joymedia.services.project_context import (
	_active_project_shots,
	_busy_shots,
	_renumber_active_shots,
	_update_project_duration_from_active_shots,
)


@frappe.whitelist()
def revise_project_storyboard(project_name, instruction=None, use_current_workflow_defaults=False):
	return frappe.get_doc("Media Project", project_name).revise_storyboard(instruction)


@frappe.whitelist()
def revise_project_shot_with_ai(project_name, shot_name, instruction):
	from joymedia.services.ai_director import revise_project_shot_with_ai as revise
	return revise(project_name, shot_name, instruction)


@frappe.whitelist()
def apply_project_shot_ai_revision(project_name, shot_name, values, regenerate=False):
	from joymedia.services.ai_director import apply_project_shot_ai_revision as apply_revision
	return apply_revision(project_name, shot_name, values, regenerate)


@frappe.whitelist()
def update_project_shot(project_name, shot_name, values):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	if isinstance(values, str):
		values = frappe.parse_json(values)
	changed = False
	if "generation_prompt" in values:
		prompt = str(values["generation_prompt"] or "").strip()
		if prompt != shot.generation_prompt and shot.name in _busy_shots(project.name):
			frappe.throw(_("This scene is still being rendered. Please wait until it is ready."))
		changed = prompt != shot.generation_prompt
		shot.generation_prompt = prompt
	caption_changed = False
	if "caption" in values:
		# Captions are drawn at export time, so they can change at any moment.
		caption = str(values["caption"] or "").strip()[:120]
		caption_changed = caption != (shot.caption or "")
		shot.caption = caption
	if changed or caption_changed:
		shot.save(ignore_permissions=True)
	if caption_changed:
		from joymedia.services.timeline_editor import _invalidate_project_output

		_invalidate_project_output(project.name)
	return {
		"name": shot.name,
		"shot_number": shot.shot_number,
		"shot_name": shot.shot_name,
		"generation_prompt": shot.generation_prompt,
		"caption": shot.caption or "",
		"is_outdated": bool(changed and shot.selected_output_asset_version),
	}


@frappe.whitelist()
def set_project_shot_keyframe(project_name, shot_name, frame_role, asset_version):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if frame_role not in ("first_frame", "last_frame"):
		frappe.throw(_("Keyframe role must be first_frame or last_frame."))
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	from joymedia.services.shot_duration_planner import ensure_shot_planning_editable
	ensure_shot_planning_editable(project.name)
	asset = frappe.db.get_value("Asset Version", asset_version, ["name", "media_asset"], as_dict=True)
	if not asset or frappe.db.get_value("Media Asset", asset.media_asset, "media_type") != "Image":
		frappe.throw(_("Keyframes must use an Image Asset Version."))
	current_asset = next(
		(row.asset_version for row in shot.generation_inputs or [] if frappe.scrub(row.reference_role or "") == frame_role),
		None,
	)
	if current_asset == asset.name:
		return {"shot_name": shot.name, "shot_number": shot.shot_number, "frame_role": frame_role, "is_outdated": False}
	shot.set("generation_inputs", [
				{"reference_role": row.reference_role, "asset_version": row.asset_version}
		for row in shot.generation_inputs or [] if frappe.scrub(row.reference_role or "") != frame_role
	])
	shot.append("generation_inputs", {"reference_role": frame_role, "asset_version": asset.name})
	shot.save(ignore_permissions=True)
	return {
		"shot_name": shot.name,
		"shot_number": shot.shot_number,
		"frame_role": frame_role,
		"is_outdated": bool(shot.selected_output_asset_version),
	}


@frappe.whitelist()
def update_project_shot_timing(project_name, shot_name, duration_seconds):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	try:
		duration_seconds = float(duration_seconds)
	except (TypeError, ValueError):
		frappe.throw(_("Shot duration must be a positive number."))
	if duration_seconds < 1:
		frappe.throw(_("Each shot must be at least 1 second long."))
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	from joymedia.services.shot_duration_planner import rebalance_shot_duration
	result = rebalance_shot_duration(project.name, shot.name, duration_seconds)
	return {"shot_name": shot.name, "shot_number": shot.shot_number, **result}


@frappe.whitelist()
def append_project_scenes(
	project_name,
	duration_seconds,
	instruction="",
	continuity=True,
	after_shot_name=None,
):
	return frappe.get_doc("Media Project", project_name).append_scenes(
		after_shot_name=after_shot_name,
		duration_seconds=duration_seconds,
		instruction=instruction,
		continuity=continuity,
	)


@frappe.whitelist()
def remove_project_scene(project_name, shot_name, confirm_continuation=False):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if frappe.db.exists(
		"Generation Run",
		{"media_project": project.name, "status": ["in", ["Queued", "Running"]]},
	):
		frappe.throw(_("Scenes cannot be removed while generation is active."))
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Scene does not belong to this project."))
	if shot.is_removed:
		return {"removed": True}

	shot_tasks = frappe.get_all("Generation Task", filters={"shot": shot.name}, pluck="name")
	confirmed = str(confirm_continuation).lower() in ("1", "true", "yes", "on")
	if shot_tasks and not confirmed:
		dependent_task = frappe.db.exists(
			"Generation Task",
			{"depends_on_task": ["in", shot_tasks]},
		)
		if dependent_task:
			return {
				"removed": False,
				"requires_confirmation": True,
				"message": _(
					"This scene has generated continuation scenes. Removing it may create a visible jump."
				),
			}

	from joymedia.services.timeline_editor import _remove_shot_timeline_clips
	_remove_shot_timeline_clips(project.name, shot.name)
	frappe.db.set_value("Shot", shot.name, "is_removed", 1, update_modified=False)
	_renumber_active_shots(project.name)
	_update_project_duration_from_active_shots(project)
	return {"removed": True}


@frappe.whitelist()
def reorder_project_shot(project_name, shot_name, target_shot_number):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	from joymedia.services.shot_duration_planner import ensure_shot_planning_editable
	ensure_shot_planning_editable(project.name)
	try:
		target_shot_number = int(target_shot_number)
	except (TypeError, ValueError):
		frappe.throw(_("Invalid shot position."))
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	shots = _active_project_shots(project.name, fields=["name", "shot_number"])
	if not shots or target_shot_number < 1 or target_shot_number > len(shots):
		frappe.throw(_("Invalid shot position."))
	ordered = [row for row in shots if row.name != shot.name]
	ordered.insert(target_shot_number - 1, next(row for row in shots if row.name == shot.name))
	for index, row in enumerate(ordered, start=1):
		frappe.db.set_value("Shot", row.name, "shot_number", -index, update_modified=False)
	for index, row in enumerate(ordered, start=1):
		frappe.db.set_value("Shot", row.name, "shot_number", index, update_modified=False)
	frappe.db.commit()
	return {"shot_name": shot.name, "shot_number": target_shot_number}


@frappe.whitelist()
def regenerate_project_shot(project_name, shot_name):
	from joymedia.services.scene_takes import regenerate_scene

	return regenerate_scene(project_name, shot_name)
