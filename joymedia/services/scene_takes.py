"""Scene takes: regenerate one scene and switch between its takes, as in Google Flow.

Every render of a scene is kept as an Asset Version of the scene's "<Shot> Output"
asset. Several scenes may be regenerated at once. Regenerating renders a new take from the scene's current prompt while the
current take stays on screen; the new take is selected once it is ready, and any
earlier take can be selected again.
"""

import json

import frappe
from frappe import _


def scene_takes(project_name, shot_name):
	"""Every take rendered for a scene, oldest first."""
	asset = frappe.db.get_value(
		"Media Asset",
		{"asset_name": f"{shot_name} Output", "media_project": project_name, "asset_scope": "Project Output"},
		"name",
	)
	if not asset:
		return []
	return frappe.get_all(
		"Asset Version", filters={"media_asset": asset}, fields=["name", "file", "creation"], order_by="creation asc"
	)


def take_position(project_name, shot):
	"""(number of takes, 1-based position of the selected take or 0) for a storyboard card."""
	names = [take.name for take in scene_takes(project_name, shot.name)]
	selected = shot.get("selected_output_asset_version")
	return len(names), names.index(selected) + 1 if selected in names else 0


@frappe.whitelist()
def regenerate_scene(project_name, shot_name):
	"""Render a new take of one scene from its current prompt."""
	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	return {**_start_takes_run(project, [shot.name]), "shot_name": shot.name}


def regenerate_scene_with_reason(project_name, shot_name, retry_reason="Manual Retry"):
	"""Render a new take and tag the run's attempts with the given retry_reason.

	Used by the QA review loop so analytics can distinguish QA-driven regenerations.
	"""
	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	result = _start_takes_run(project, [shot.name], retry_reason=retry_reason)
	return {**result, "shot_name": shot.name}


@frappe.whitelist()
def render_final(project_name):
	"""Re-render every scene of a fast draft at full quality, as new takes.

	The draft takes stay as earlier takes of each scene; transitions and music follow
	automatically once the new takes are ready.
	"""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	from joymedia.services.project_context import _active_project_shots, _busy_shots
	from joymedia.services.storyboard_job import planning_status

	if planning_status(project.name) == "Running" or _busy_shots(project.name):
		frappe.throw(_("Scenes are still being rendered. Please wait until they are ready."))
	shots = [shot.name for shot in _active_project_shots(project.name, fields=["name"])]
	if not shots:
		frappe.throw(_("Generate a storyboard first."))
	project.save_video_settings(
		project.total_duration_seconds, project.delivery_preset,
		generation_mode=project.generation_mode, reference_mode=project.reference_mode, quality_mode="Production",
	)
	project.reload()
	return _start_takes_run(project, shots)


def _start_takes_run(project, shot_names, retry_reason=None):
	"""A run that renders new takes of these scenes, replacing each one's take when ready."""
	from joymedia.services.project_context import build_project_snapshot
	from joymedia.services.generation_orchestrator import start_run_internal
	from joymedia.services.generation_pipeline_service import get_pipeline_steps, pipeline_for_final_workflow

	snapshot_json, snapshot_hash = build_project_snapshot(project)
	# Regeneration must use the same selected keyframe→video pipeline as the
	# original run.  Re-resolve only when a project was changed to a compatible
	# workflow, never by model-name convention.
	pipeline_name = project.generation_pipeline or None
	if pipeline_name and get_pipeline_steps(pipeline_name)[-1].workflow != project.workflow:
		pipeline_name = None
	if not pipeline_name:
		pipeline = pipeline_for_final_workflow(project.workflow)
		pipeline_name = pipeline.name if pipeline else None
	run = frappe.get_doc(
		{
			"doctype": "Generation Run",
			"media_project": project.name,
			"project_snapshot_json": snapshot_json,
			"project_snapshot_hash": snapshot_hash,
			# replace_selection: each new take replaces the current one once it is ready.
			"execution_scope_json": json.dumps({
				"shot_names": shot_names,
				"replace_selection": True,
				"retry_reason": retry_reason or None,
			}),
			"workflow": project.workflow,
			"generation_pipeline": pipeline_name,
			"requested_by": frappe.session.user,
			"status": "Draft",
		}
	).insert(ignore_permissions=True)
	result = start_run_internal(run.name)
	frappe.db.commit()
	return {"run": run.name, "status": result["status"]}


@frappe.whitelist()
def select_scene_take(project_name, shot_name, take_index):
	"""Use take number take_index (1 = oldest) of a scene, then redo the film's transitions and music."""
	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	takes = scene_takes(project.name, shot.name)
	take_index = int(take_index)
	if not 1 <= take_index <= len(takes):
		frappe.throw(_("This scene has no take {0}.").format(take_index))
	shot.db_set("selected_output_asset_version", takes[take_index - 1].name, update_modified=False)
	from joymedia.api.reviews import sync_shot_review_status
	sync_shot_review_status(shot.name)
	from joymedia.services.post_production import queue_post_production_internal

	queue_post_production_internal(project.name)
	frappe.db.commit()
	count, position = take_position(project.name, shot)
	return {"shot_name": shot.name, "take_count": count, "take_index": position}


def _project_shot(project_name, shot_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."), frappe.PermissionError)
	if shot.is_removed:
		frappe.throw(_("Removed scenes cannot be regenerated."))
	return project, shot


def _ensure_scene_free(project, shot):
	"""A scene can change unless it is rendering or the storyboard is being written.

	Several scenes may render at once; finishing repeats until it includes every change.
	"""
	from joymedia.services.project_context import _busy_shots
	from joymedia.services.storyboard_job import planning_status

	if planning_status(project.name) == "Running":
		frappe.throw(_("The storyboard is still being written. Please wait until it is ready."))
	if shot.name in _busy_shots(project.name):
		frappe.throw(_("This scene is still being rendered. Please wait until it is ready."))
