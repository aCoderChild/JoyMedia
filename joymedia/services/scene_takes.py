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


def _start_takes_run(project, shot_names, retry_reason=None, stage=None):
	"""A run that renders new takes of these scenes, replacing each one's take when ready.

	With stage="keyframe" it draws only the scenes' first frames, for review before any video."""
	if project.storyboard_approval_status != "Approved":
		frappe.throw(_("Review and approve the storyboard before generating another take."))
	from joymedia.services.project_context import build_project_snapshot
	from joymedia.services.generation_orchestrator import start_run_internal
	from joymedia.services.plan_signature import assert_plan_matches_approval, compute_plan_signature

	assert_plan_matches_approval(project)

	snapshot_json, snapshot_hash = build_project_snapshot(project, require_production_pipeline=True)
	# The snapshot selected the production pipeline once. Reuse that immutable
	# choice rather than re-reading the active setting after a possible promotion.
	pipeline_name = (frappe.parse_json(snapshot_json) or {}).get("generation_pipeline")
	if not pipeline_name:
		frappe.throw(_("Generation requires an explicitly promoted Generation Pipeline."))
	continuation_from_task = None if stage == "keyframe" else _continuation_source_task(project, shot_names)
	run = frappe.get_doc(
		{
			"doctype": "Generation Run",
			"media_project": project.name,
			"project_snapshot_json": snapshot_json,
			"project_snapshot_hash": snapshot_hash,
			# replace_selection: each new take replaces the current one once it is ready.
			"execution_scope_json": json.dumps({
				"shot_names": shot_names,
				"replace_selection": stage != "keyframe",
				"stage": stage,
				"retry_reason": retry_reason or None,
				"continuation_from_task": continuation_from_task,
				"plan_signature": compute_plan_signature(project.name),
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


def _continuation_source_task(project, shot_names):
	"""Freeze an independently regenerated continuing shot to its selected predecessor.

	A continuation cannot safely invent a new first frame. Its predecessor must
	have an approved selected output backed by a completed Generation Attempt and
	a durable Last Frame artifact.
	"""
	if len(shot_names) != 1:
		return None
	shot = frappe.get_doc("Shot", shot_names[0])
	if shot.continuity_mode != "Continue":
		return None
	previous = frappe.get_all(
		"Shot",
		filters={
			"media_project": project.name,
			"is_removed": 0,
			"shot_number": ["<", shot.shot_number],
		},
		fields=["name", "selected_output_asset_version", "review_status"],
		order_by="shot_number desc, name desc",
		limit=1,
	)
	if not previous:
		frappe.throw(_("A continuing scene needs a preceding scene."))
	previous = previous[0]
	if not previous.selected_output_asset_version or previous.review_status != "Approved":
		frappe.throw(_("The preceding scene needs an approved selected output before this continuation can regenerate."))
	attempt_name = frappe.db.get_value(
		"Asset Version", previous.selected_output_asset_version, "source_generation_attempt"
	)
	if not attempt_name:
		frappe.throw(_("The preceding scene output has no generation lineage for frame continuation."))
	task_name = frappe.db.get_value("Generation Attempt", attempt_name, "generation_task")
	if not task_name or not frappe.db.exists(
		"Generation Artifact", {"generation_attempt": attempt_name, "artifact_role": "Last Frame", "frappe_file": ["is", "set"]}
	):
		frappe.throw(_("The preceding scene has no usable Last Frame artifact for continuation."))
	return task_name


@frappe.whitelist()
def select_scene_take(project_name, shot_name, take_index):
	"""Use take number take_index (1 = oldest) of a scene, then redo the film's transitions and music."""
	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	takes = scene_takes(project.name, shot.name)
	take_index = int(take_index)
	if not 1 <= take_index <= len(takes):
		frappe.throw(_("This scene has no take {0}.").format(take_index))
	selected_output = takes[take_index - 1].name
	selection_changed = shot.selected_output_asset_version != selected_output
	shot.db_set("selected_output_asset_version", selected_output, update_modified=False)
	from joymedia.api.reviews import sync_shot_review_status
	sync_shot_review_status(shot.name)
	stale_shots = mark_stale_downstream_shots(shot) if selection_changed else []
	from joymedia.services.post_production import resume_post_production_if_approved

	frappe.db.commit()
	# An unapproved take is still a legitimate editorial selection. Keep it
	# selected for review, and only resume finishing once QA permits delivery.
	try:
		finishing = resume_post_production_if_approved(project.name) if selection_changed else {"status": "Unchanged"}
	except Exception:
		# The take selection is durable. Finishing can be retried independently.
		frappe.logger("joymedia.scene_takes").exception("Unable to resume finishing for %s", project.name)
		finishing = {"status": "Deferred"}
	count, position = take_position(project.name, shot)
	return {
		"shot_name": shot.name,
		"take_count": count,
		"take_index": position,
		"finishing": finishing["status"],
		"stale_shots": stale_shots,
	}


def mark_stale_downstream_shots(shot):
	"""Flag shots whose selected output was generated from a different take of `shot`.

	Dependencies come from stored Generation Task lineage, never from shot order:
	a downstream selected output is stale when its task depends on a task of
	`shot` other than the one that produced the take now selected.
	"""
	selected_attempt = frappe.db.get_value(
		"Asset Version", shot.selected_output_asset_version, "source_generation_attempt"
	)
	selected_task = (
		frappe.db.get_value("Generation Attempt", selected_attempt, "generation_task") if selected_attempt else None
	)
	upstream_tasks = frappe.get_all("Generation Task", filters={"shot": shot.name}, pluck="name")
	if not upstream_tasks:
		return []
	stale = []
	for task in frappe.get_all(
		"Generation Task",
		filters={"depends_on_task": ["in", upstream_tasks], "shot": ["!=", shot.name]},
		fields=["name", "shot", "depends_on_task"],
	):
		if task.depends_on_task == selected_task or task.shot in stale:
			continue
		downstream = frappe.db.get_value(
			"Shot", task.shot, ["selected_output_asset_version", "media_project", "is_removed"], as_dict=True
		)
		if not downstream or downstream.is_removed or downstream.media_project != shot.media_project:
			continue
		attempt = frappe.db.get_value(
			"Asset Version", downstream.selected_output_asset_version, "source_generation_attempt"
		) if downstream.selected_output_asset_version else None
		if attempt and frappe.db.get_value("Generation Attempt", attempt, "generation_task") == task.name:
			frappe.db.set_value("Shot", task.shot, "review_status", "Needs Revision", update_modified=False)
			stale.append(task.shot)
	return stale


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
