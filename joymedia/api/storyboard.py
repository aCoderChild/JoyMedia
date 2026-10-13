# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt


"""HTTP endpoints for storyboard import, revision, shots, scenes and reordering."""

import json
from pathlib import Path

import frappe
from frappe import _
from joymedia.services.project_context import (
	_active_project_shots,
	_busy_shots,
	_renumber_active_shots,
	_update_project_duration_from_active_shots,
)


@frappe.whitelist()
def import_storyboard_workbook(project_name, workbook_file, demo_name=None):
	"""Import one editable demo from an uploaded XLSX; never start rendering."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if frappe.db.exists("Generation Run", {"media_project": project.name}):
		frappe.throw(_("A storyboard with generation history cannot be replaced. Create a new project revision."))
	file_doc = frappe.get_doc("File", workbook_file)
	file_doc.check_permission("read")
	if Path(file_doc.file_name or "").suffix.lower() != ".xlsx":
		frappe.throw(_("Storyboard import requires an .xlsx workbook."))
	if int(file_doc.file_size or 0) > 10 * 1024 * 1024:
		frappe.throw(_("Storyboard workbook must be 10 MB or smaller."))
	from joymedia.services.storyboard_workbook import parse_storyboard_workbook
	try:
		parsed = parse_storyboard_workbook(file_doc.get_full_path())
	except (OSError, ValueError) as exc:
		frappe.throw(_("Could not read the storyboard workbook: {0}").format(str(exc)))
	demo = next(
		(item for item in parsed["demos"] if item["name"].casefold() == str(demo_name or "Demo 1").casefold()),
		None,
	)
	if not demo:
		available = ", ".join(item["name"] for item in parsed["demos"])
		frappe.throw(_("Storyboard demo '{0}' was not found. Available sheets: {1}.").format(demo_name, available))
	for shot_name in frappe.get_all("Shot", filters={"media_project": project.name}, pluck="name"):
		frappe.delete_doc("Shot", shot_name, ignore_permissions=True)
	for position, scene in enumerate(demo["scenes"], start=1):
		prompt = _imported_scene_prompt(scene)
		frappe.get_doc({
			"doctype": "Shot",
			"media_project": project.name,
			"shot_number": position,
			"shot_name": scene["beat_name"],
			"storyboard_beat": scene["beat_name"],
			"source_timing": scene["source_timing"],
			"source_start_seconds": scene["start_seconds"],
			"source_end_seconds": scene["end_seconds"],
			"duration_seconds": scene["duration_seconds"],
			"continuity_mode": scene["continuity_mode"],
			"generation_prompt": prompt,
			"image_prompt": _imported_image_prompt(scene),
			"caption": scene["on_screen_text"][:120],
			"voice_over": scene["voice_over"],
			"audio_cues": scene["audio_cues"],
		}).insert(ignore_permissions=True)
	metadata = demo["metadata"]
	project.storyboard_source_file = file_doc.name
	project.storyboard_source_json = json.dumps({"selected_demo": demo, "all_demos": parsed["demos"]}, ensure_ascii=False)
	project.storyboard_timing_warnings = json.dumps(demo["timing_warnings"], ensure_ascii=False)
	project.storyboard_approval_status = "Ready for Review"
	project.product_name = metadata.get("product_name") or project.product_name
	if not (project.video_idea or "").strip():
		project.video_idea = "\n".join(filter(None, (metadata.get("objective"), metadata.get("tone_mood"))))
	if metadata.get("duration"):
		from joymedia.services.storyboard_workbook import parse_duration_seconds
		project.total_duration_seconds = parse_duration_seconds(metadata["duration"]) or project.total_duration_seconds
	project.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"project": project.name,
		"demo": demo["name"],
		"shot_count": len(demo["scenes"]),
		"timing_warnings": demo["timing_warnings"],
		"approval_status": project.storyboard_approval_status,
	}


@frappe.whitelist()
def approve_project_storyboard(project_name, acknowledge_timing_warnings=False, shot_references=None):
	"""Approve the storyboard; `shot_references` maps a shot name to the reference keys it needs.

	Shots without an explicit assignment fall back to every selected project image.
	"""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if not frappe.db.exists("Shot", {"media_project": project.name, "is_removed": 0}):
		frappe.throw(_("Import or create a storyboard before approval."))
	if not str(project.video_idea or "").strip():
		frappe.throw(_("A non-empty video idea is required before approving a storyboard."))
	warnings = frappe.parse_json(project.storyboard_timing_warnings or "[]")
	if warnings and str(acknowledge_timing_warnings).lower() not in {"1", "true", "yes", "on"}:
		frappe.throw(_("Resolve or explicitly acknowledge the storyboard timing warnings before approval."))
	assigned = _assign_shot_references(project, frappe.parse_json(shot_references) if shot_references else {})
	_bind_unassigned_project_references(project, skip=assigned)
	_validate_shot_reference_contracts(project)
	from joymedia.services.plan_signature import compute_plan_signature

	project.storyboard_approval_status = "Approved"
	project.approved_plan_signature = compute_plan_signature(project.name)
	project.save(ignore_permissions=True)
	return {"project": project.name, "approval_status": project.storyboard_approval_status}


def _imported_scene_prompt(scene):
	return "\n".join(filter(None, (scene.get("visual_camera"), scene.get("action"), scene.get("audio_cues")))).strip()


def _imported_image_prompt(scene):
	return "\n".join(filter(None, (scene.get("visual_camera"), scene.get("action")))).strip()


def _mark_storyboard_needs_review(project):
	"""Invalidate a prior approval whenever an editable storyboard changes."""
	if project.storyboard_approval_status == "Approved":
		project.db_set("storyboard_approval_status", "Ready for Review", update_modified=False)
		project.storyboard_approval_status = "Ready for Review"


@frappe.whitelist()
def plan_project_production(project_name, shot_names=None, apply=True):
	"""Turn the storyboard's creative beats into production shots (prompts, continuity, references).

	Timing, voice-over, on-screen text and the imported source stay as written. The result is a
	proposal for the user to review before approval; with apply=False nothing is saved.
	"""
	from joymedia.services import production_planner

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	from joymedia.services.shot_duration_planner import ensure_shot_planning_editable
	ensure_shot_planning_editable(project.name)
	apply = str(apply).lower() in {"1", "true", "yes", "on"}
	wanted = set(frappe.parse_json(shot_names)) if isinstance(shot_names, str) and shot_names else set(shot_names or [])
	busy = _busy_shots(project.name)
	shots = [
		frappe.get_doc("Shot", name)
		for name in frappe.get_all(
			"Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name", order_by="shot_number asc"
		)
	]
	references = production_planner.project_reference_options(project)
	results, previous_end_state = [], ""
	for shot in shots:
		if wanted and shot.name not in wanted:
			previous_end_state = shot.end_state or ""
			continue
		if shot.name in busy:
			frappe.throw(_("Scene {0} is still being rendered. Please wait until it is ready.").format(shot.shot_name))
		plan = production_planner.plan_production_shot(
			project, shot, previous_end_state=previous_end_state, references=references
		)
		if apply and not plan["held_back"]:
			production_planner.apply_production_shot(project, shot, plan)
		previous_end_state = plan["end_state"]
		results.append({"shot": shot.name, "shot_name": shot.shot_name, **plan})
	if apply and any(not result["held_back"] for result in results):
		_mark_storyboard_needs_review(project)
		frappe.db.commit()
	return results


@frappe.whitelist()
def set_project_shot_references(project_name, shot_name, reference_keys):
	"""Choose which project references one scene is generated from."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if shot_name in _busy_shots(project.name):
		frappe.throw(_("This scene is still being rendered. Please wait until it is ready."))
	keys = frappe.parse_json(reference_keys) if isinstance(reference_keys, str) else reference_keys
	if not isinstance(keys, list):
		frappe.throw(_("Reference keys must be a list."))
	_assign_shot_references(project, {shot_name: keys})
	_mark_storyboard_needs_review(project)
	frappe.db.commit()
	return {"shot_name": shot_name, "reference_keys": keys}


def _assign_shot_references(project, assignments):
	"""Replace the references of the named shots with the explicitly chosen project references."""
	if not isinstance(assignments, dict):
		frappe.throw(_("Shot references must map each shot to a list of reference keys."))
	rows = {row.reference_key: row for row in project.selected_media or []}
	for shot_name, keys in assignments.items():
		shot = frappe.get_doc("Shot", shot_name)
		if shot.media_project != project.name or shot.is_removed:
			frappe.throw(_("Shot {0} does not belong to this project.").format(shot_name))
		unknown = [key for key in keys if key not in rows]
		if unknown:
			frappe.throw(_("Unknown project reference(s) for {0}: {1}").format(shot_name, ", ".join(unknown)))
		shot.set("generation_inputs", [])
		for key in keys:
			shot.append("generation_inputs", {
				"reference_role": rows[key].reference_role or "General", "asset_version": rows[key].asset_version,
			})
		shot.save(ignore_permissions=True)
	return set(assignments)


def _validate_shot_reference_contracts(project):
	"""Reject, before any GPU time, shots whose references the first pipeline stage cannot take.

	Every problem across the storyboard is reported together so the user can fix the
	assignments in one pass.
	"""
	if not project.workflow:
		return
	from joymedia.services.generation_orchestrator import _pipeline_reference_inputs
	from joymedia.services.workflow_resolver import get_workflow_input_contract
	from joymedia.services.workflow_routing import resolve_shot_render_route

	default_workflow = frappe.get_doc("Generation Workflow", project.workflow)
	errors = []
	for shot_name in frappe.get_all(
		"Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name", order_by="shot_number asc"
	):
		shot = frappe.get_doc("Shot", shot_name)
		references = [
			{"reference_role": row.reference_role, "asset_version": row.asset_version}
			for row in shot.generation_inputs or []
		]
		try:
			route = resolve_shot_render_route(
				default_workflow, references, handoff_type=shot.handoff_type or "",
				pipeline_name=project.generation_pipeline or None,
			)
			if not route["generation_pipeline"]:
				continue
			first_stage = frappe.get_doc(
				"Generation Workflow", frappe.get_doc("Generation Pipeline", route["generation_pipeline"]).steps[0].workflow
			)
			mapped = _pipeline_reference_inputs(frappe._dict(references=route["references"]), first_stage)
			# A continuing shot starts from its predecessor's last frame, not from a keyframe.
			continues = shot.continuity_mode == "Continue" and shot.shot_number > 1
			for item in [] if continues else get_workflow_input_contract(first_stage):
				if item.get("required") and item["role"] != "first_frame" and not mapped.get(item["role"]):
					frappe.throw(_("no reference is assigned for the required role '{0}'.").format(item["role"]))
		except frappe.ValidationError as exc:
			errors.append(f"{shot.shot_name or shot.name}: {frappe.utils.strip_html(str(exc))}")
	if errors:
		frappe.throw("<br>".join([_("Fix these shot reference assignments before approval:")] + errors))


def _bind_unassigned_project_references(project, skip=()):
	"""Persist selected image references on imported shots that have none yet.

	The importer cannot infer creative meaning from an arbitrary workbook. This
	general fallback keeps the project's explicit reference selections durable and
	editable, while route validation enforces the promoted workflow's contract.
	"""
	references = []
	for row in project.selected_media or []:
		media_asset = frappe.db.get_value("Asset Version", row.asset_version, "media_asset")
		if media_asset and frappe.db.get_value("Media Asset", media_asset, "media_type") == "Image":
			references.append((row.reference_role or "General", row.asset_version))
	if not references:
		return
	for shot_name in frappe.get_all("Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name"):
		shot = frappe.get_doc("Shot", shot_name)
		if shot_name in skip or shot.generation_inputs:
			continue
		for role, asset_version in references:
			shot.append("generation_inputs", {"reference_role": role, "asset_version": asset_version})
		shot.save(ignore_permissions=True)


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
	image_prompt_changed = False
	if "generation_prompt" in values:
		prompt = str(values["generation_prompt"] or "").strip()
		if prompt != shot.generation_prompt and shot.name in _busy_shots(project.name):
			frappe.throw(_("This scene is still being rendered. Please wait until it is ready."))
		changed = prompt != shot.generation_prompt
		shot.generation_prompt = prompt
	if "image_prompt" in values and hasattr(shot, "image_prompt"):
		image_prompt = str(values["image_prompt"] or "").strip()
		if image_prompt != (shot.image_prompt or "") and shot.name in _busy_shots(project.name):
			frappe.throw(_("This scene is still being rendered. Please wait until it is ready."))
		image_prompt_changed = image_prompt != (shot.image_prompt or "")
		shot.image_prompt = image_prompt
	caption_changed = False
	if "caption" in values:
		# Captions are drawn at export time, so they can change at any moment.
		caption = str(values["caption"] or "").strip()[:120]
		caption_changed = caption != (shot.caption or "")
		shot.caption = caption
	if "continuity_mode" in values:
		continuity_mode = str(values["continuity_mode"] or "").strip()
		if continuity_mode not in {"Continue", "New Scene"}:
			frappe.throw(_("Continuity mode must be Continue or New Scene."))
		if continuity_mode == "Continue" and int(shot.shot_number or 0) <= 1:
			frappe.throw(_("The first scene cannot continue from a previous scene."))
		continuity_changed = continuity_mode != (shot.continuity_mode or "New Scene")
		if continuity_changed and shot.name in _busy_shots(project.name):
			frappe.throw(_("This scene is still being rendered. Please wait until it is ready."))
		shot.continuity_mode = continuity_mode
	else:
		continuity_changed = False
	if changed or image_prompt_changed or caption_changed or continuity_changed:
		shot.save(ignore_permissions=True)
	# Captions are finishing-only; the approved plan signature already covers generation inputs.
	if changed or image_prompt_changed or continuity_changed:
		_mark_storyboard_needs_review(project)
	if caption_changed:
		from joymedia.services.timeline_editor import _invalidate_project_output

		_invalidate_project_output(project.name)
	return {
		"name": shot.name,
		"shot_number": shot.shot_number,
		"shot_name": shot.shot_name,
		"generation_prompt": shot.generation_prompt,
		"image_prompt": getattr(shot, "image_prompt", None) or shot.generation_prompt,
		"caption": shot.caption or "",
		"continuity_mode": shot.continuity_mode or "New Scene",
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
	_mark_storyboard_needs_review(project)
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
	_mark_storyboard_needs_review(project)
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
	_mark_storyboard_needs_review(project)
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
	# Nothing precedes the new first shot, so it cannot continue from one.
	first = ordered[0]
	if frappe.db.get_value("Shot", first.name, "continuity_mode") == "Continue":
		frappe.db.set_value("Shot", first.name, "continuity_mode", "New Scene", update_modified=False)
		frappe.msgprint(_("Shot {0} is now first, so its continuity was reset to New Scene.").format(first.name))
	_mark_storyboard_needs_review(project)
	frappe.db.commit()
	return {"shot_name": shot.name, "shot_number": target_shot_number}


@frappe.whitelist()
def regenerate_project_shot(project_name, shot_name):
	from joymedia.services.scene_takes import regenerate_scene

	return regenerate_scene(project_name, shot_name)
