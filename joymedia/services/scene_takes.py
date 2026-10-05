"""Scene takes: regenerate one scene and switch between its takes, as in Google Flow.

Every render of a scene is kept as an Asset Version of the scene's "<Shot> Output"
asset. Regenerating renders a new take from the scene's current prompt while the
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
	_ensure_idle(project)
	from joymedia.joymedia.doctype.media_project.media_project import build_project_snapshot
	from joymedia.services.generation_orchestrator import start_run_internal

	snapshot_json, snapshot_hash = build_project_snapshot(project)
	run = frappe.get_doc(
		{
			"doctype": "Generation Run",
			"media_project": project.name,
			"project_snapshot_json": snapshot_json,
			"project_snapshot_hash": snapshot_hash,
			# replace_selection: the new take replaces the current one once it is ready.
			"execution_scope_json": json.dumps({"shot_names": [shot.name], "replace_selection": True}),
			"workflow": project.workflow,
			"requested_by": frappe.session.user,
			"status": "Draft",
		}
	).insert(ignore_permissions=True)
	result = start_run_internal(run.name)
	frappe.db.commit()
	return {"run": run.name, "status": result["status"], "shot_name": shot.name}


@frappe.whitelist()
def select_scene_take(project_name, shot_name, take_index):
	"""Use take number take_index (1 = oldest) of a scene, then redo the film's transitions and music."""
	project, shot = _project_shot(project_name, shot_name)
	_ensure_idle(project)
	takes = scene_takes(project.name, shot.name)
	take_index = int(take_index)
	if not 1 <= take_index <= len(takes):
		frappe.throw(_("This scene has no take {0}.").format(take_index))
	shot.db_set("selected_output_asset_version", takes[take_index - 1].name, update_modified=False)
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


def _ensure_idle(project):
	"""One render at a time per project, so the finished film always includes every change."""
	if frappe.db.exists("Generation Run", {"media_project": project.name, "status": ["in", ["Queued", "Running"]]}):
		frappe.throw(_("A scene is still being rendered. Please wait until it is ready."))
	from joymedia.services.post_production import get_post_production_status

	if get_post_production_status(project.name)["status"] in ("Queued", "Running"):
		frappe.throw(_("Transitions and music are still being added. Please wait until they are ready."))
