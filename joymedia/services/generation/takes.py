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
		"Asset Version",
		filters={"media_asset": asset},
		fields=["name", "file", "creation"],
		order_by="creation asc",
	)


def take_position(project_name, shot):
	"""(number of takes, 1-based position of the selected take or 0) for a storyboard card."""
	names = [take.name for take in scene_takes(project_name, shot.name)]
	selected = shot.get("selected_output_asset_version")
	return len(names), names.index(selected) + 1 if selected in names else 0


@frappe.whitelist()
def regenerate_scene(project_name, shot_name, automatic=False, seed=None):
	"""Render a new take of one scene from its current prompt (`automatic`: asked by the consistency check)."""
	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	return {
		**_start_takes_run(
			project, [shot.name], reset_review_retries=not automatic, video_seed=_video_seed(seed)
		),
		"shot_name": shot.name,
	}


def _video_seed(value):
	"""Freeze an optional reproducible video seed without changing client defaults."""
	if value is None:
		return None
	if type(value) is not int or not 0 <= value < 2_147_483_648:
		frappe.throw(_("Video seed must be an integer from 0 to 2147483647."))
	return value


def regenerate_scene_with_reason(project_name, shot_name, retry_reason="Manual Retry"):
	"""Render a new take and tag the run's attempts with the given retry_reason.

	Used by the QA review loop so analytics can distinguish QA-driven regenerations.
	"""
	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	result = _start_takes_run(project, [shot.name], retry_reason=retry_reason)
	return {**result, "shot_name": shot.name}


def _start_takes_run(
	project,
	shot_names,
	retry_reason=None,
	stage=None,
	reset_review_retries=False,
	keyframe_seed=None,
	video_seed=None,
):
	"""Serialize short admission decisions while GPU jobs remain independent.

	Two tabs must not both pass the scene-free check or hold Shot/Series rows
	while waiting for the other request. Redis coordinates admission across app
	workers; this lock is released when the run is durably queued, before inference.
	"""
	if retry_reason:
		choices = (frappe.get_meta("Generation Attempt").get_field("retry_reason").options or "").splitlines()
		if retry_reason not in choices:
			frappe.throw(_("Choose a configured retry reason before starting generation."))
	frappe.db.commit()
	lock = frappe.cache.lock(
		f"joymedia-take-admission:{frappe.local.site}:{project.name}",
		timeout=600,
		blocking_timeout=120,
	)
	if not lock.acquire():
		frappe.throw(_("Another generation request is being prepared. Please try again shortly."))
	try:
		frappe.db.commit()  # discard the read snapshot from before waiting
		project.reload()
		for shot_name in shot_names:
			_ensure_scene_free(project, frappe.get_doc("Shot", shot_name))
		if reset_review_retries:
			from joymedia.services.review.consistency import reset_redos

			for shot_name in shot_names:
				reset_redos(shot_name)
		return _start_takes_run_locked(
			project,
			shot_names,
			retry_reason=retry_reason,
			stage=stage,
			video_seed=video_seed,
			**({"keyframe_seed": keyframe_seed} if keyframe_seed is not None else {}),
		)
	finally:
		lock.release()


def _start_takes_run_locked(
	project, shot_names, retry_reason=None, stage=None, keyframe_seed=None, video_seed=None
):
	"""A run that renders new takes of these scenes, replacing each one's take when ready.

	With stage="keyframe" it draws only the scenes' first frames, for review before any video."""
	if project.storyboard_approval_status != "Approved":
		frappe.throw(_("Review and approve the storyboard before generating another take."))
	if stage == "keyframe":
		from joymedia.services.planning.pose_coverage import assert_opening_character_references

		assert_opening_character_references(frappe.get_doc("Shot", name) for name in shot_names)
	from joymedia.services.generation.orchestrator import start_run_internal, validate_run_preflight
	from joymedia.services.planning.signature import assert_plan_matches_approval, compute_plan_signature
	from joymedia.services.project.context import build_project_snapshot

	# Like a whole film, a take or first frame follows the pipeline the site now uses (re-sealed: not an edit of the plan).
	matched = (
		bool(project.get("approved_plan_signature"))
		and compute_plan_signature(project.name) == project.approved_plan_signature
	)
	project.follow_active_pipeline()
	if matched:
		project.reload()
		project.db_set("approved_plan_signature", compute_plan_signature(project.name), update_modified=False)
	assert_plan_matches_approval(project)

	snapshot_json, snapshot_hash = build_project_snapshot(
		project, require_production_pipeline=True, keyframe_stage=stage == "keyframe"
	)
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
			"execution_scope_json": json.dumps(
				{
					"shot_names": shot_names,
					"replace_selection": stage != "keyframe",
					"stage": stage,
					"retry_reason": retry_reason or None,
					"continuation_from_task": continuation_from_task,
					"plan_signature": compute_plan_signature(project.name),
					**({"video_seed": _video_seed(video_seed)} if video_seed is not None else {}),
					**(
						{"keyframe_seed": keyframe_seed}
						if stage == "keyframe" and keyframe_seed is not None
						else {}
					),
				}
			),
			"workflow": project.workflow,
			"generation_pipeline": pipeline_name,
			"requested_by": frappe.session.user,
			"status": "Draft",
		}
	)
	validate_run_preflight(run, project)
	run.insert(ignore_permissions=True)
	result = start_run_internal(run.name, preflight_checked=True)
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
		fields=["name", "selected_output_asset_version"],
		order_by="shot_number desc, name desc",
		limit=1,
	)
	if not previous:
		frappe.throw(_("A continuing scene needs a preceding scene."))
	previous = previous[0]
	if not previous.selected_output_asset_version:
		frappe.throw(
			_("The preceding scene needs a generated output before this continuation can regenerate.")
		)
	attempt_name = frappe.db.get_value(
		"Asset Version", previous.selected_output_asset_version, "source_generation_attempt"
	)
	if not attempt_name:
		frappe.throw(_("The preceding scene output has no generation lineage for frame continuation."))
	task_name = frappe.db.get_value("Generation Attempt", attempt_name, "generation_task")
	if not task_name or not frappe.db.exists(
		"Generation Artifact",
		{"generation_attempt": attempt_name, "artifact_role": "Last Frame", "frappe_file": ["is", "set"]},
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
	stale_shots = stale_downstream_shots(shot) if selection_changed else []
	from joymedia.services.editing.post_production import resume_post_production

	frappe.db.commit()
	try:
		if not selection_changed:
			finishing = {"status": "Unchanged"}
		elif frappe.flags.get("joymedia_defer_finishing"):
			finishing = {"status": "Deferred"}
		else:
			finishing = resume_post_production(project.name)
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


def stale_downstream_shots(shot):
	"""Shots whose selected output was generated from a different take of `shot`.

	Dependencies come from stored Generation Task lineage, never from shot order:
	a downstream selected output is stale when its task depends on a task of
	`shot` other than the one that produced the take now selected.
	"""
	selected_attempt = frappe.db.get_value(
		"Asset Version", shot.selected_output_asset_version, "source_generation_attempt"
	)
	selected_task = (
		frappe.db.get_value("Generation Attempt", selected_attempt, "generation_task")
		if selected_attempt
		else None
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
		attempt = (
			frappe.db.get_value(
				"Asset Version", downstream.selected_output_asset_version, "source_generation_attempt"
			)
			if downstream.selected_output_asset_version
			else None
		)
		if attempt and frappe.db.get_value("Generation Attempt", attempt, "generation_task") == task.name:
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
	from joymedia.services.planning.jobs import planning_status
	from joymedia.services.project.context import _busy_shots

	if planning_status(project.name) == "Running":
		frappe.throw(_("The storyboard is still being written. Please wait until it is ready."))
	if shot.name in _busy_shots(project.name):
		frappe.throw(_("This scene is still being rendered. Please wait until it is ready."))


@frappe.whitelist(methods=["POST"])
def retain_held_take_for_review(
	project_name,
	shot_name,
	attempt_name,
	expected_current,
	expected_source_sha256,
	review_note,
	review_artifact=None,
):
	"""Keep action-qualified held footage as a separate, unselected review take.

	This never changes the failed attempt, machine findings or selected output.
	Uncertain action/physical/continuity verdicts are eligible because the
	reviewer watched the footage; identity or cast gaps and every witnessed
	violation remain blocking.
	"""
	import tempfile
	from pathlib import Path

	from joymedia.services.consistency.repair import held_take_review_candidate
	from joymedia.services.editing import composer as c
	from joymedia.services.project.context import _sheet_scenes
	from joymedia.services.review.admission import digest, report_for
	from joymedia.services.scene.direction import authored_action, direction_changed

	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	if shot.selected_output_asset_version != expected_current:
		frappe.throw(_("The selected take changed. Reload the scene history."))
	if not isinstance(review_note, str) or not review_note.strip() or len(review_note) > 2000:
		frappe.throw(_("Describe the evidence to inspect in this held take."))
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	task = frappe.get_doc("Generation Task", attempt.generation_task)
	terminal = {"Failed", "Cancelled"} if review_artifact else {"Failed"}
	if task.shot != shot.name or attempt.status not in terminal or task.status not in terminal:
		frappe.throw(_("Choose a held attempt from this scene."))
	run = frappe.get_doc("Generation Run", task.generation_run)
	if run.media_project != project.name or run.status not in terminal:
		frappe.throw(_("The held attempt does not belong to this failed project run."))
	original_report = report_for(attempt.name)
	report = original_report
	if review_artifact:
		from joymedia.services.review.recheck import checked_recheck

		report = checked_recheck(review_artifact, attempt.name, original_report)
	if not report or not held_take_review_candidate(report):
		frappe.throw(_("Resolve cast, identity or witnessed violations before retaining this take."))
	artifact = frappe.get_doc(
		"Generation Artifact", {"generation_attempt": attempt.name, "artifact_role": "Primary Video"}
	)
	path = c._get_artifact_path(artifact)
	content_hash = digest(Path(path).read_bytes())
	if (
		content_hash != expected_source_sha256
		or content_hash != report.get("source_sha256")
		or digest(run.project_snapshot_json.encode()) != report.get("snapshot_sha256")
		or report.get("artifact") != artifact.name
	):
		frappe.throw(_("Held footage or its frozen review evidence changed."))
	scene = next(s for s in json.loads(run.project_snapshot_json)["shots"] if s["shot"] == shot.name)
	current = shot.as_dict()
	current["references"] = [r.as_dict() for r in shot.generation_inputs]
	current["authored_action"] = authored_action(
		shot, _sheet_scenes(project).get((shot.storyboard_beat or "", shot.source_timing or ""))
	)
	if direction_changed(current, scene):
		frappe.throw(_("Scene direction changed since this held inference."))
	tasks = frappe.get_all(
		"Generation Task", filters={"generation_run": run.name, "shot": shot.name}, pluck="name"
	)
	if tasks != [task.name]:
		frappe.throw(_("Review held segments individually before assembling a chained scene."))
	asset = c._get_or_create_shot_output_asset(shot, project.name)
	frappe.db.commit()
	profile = c._get_delivery_profile(project, run.name)
	frames = c._shot_frame_count(shot, profile)
	with tempfile.TemporaryDirectory(prefix="joymedia-held-take-") as directory:
		output = Path(directory) / "review.mp4"
		c._normalize_segment(path, output, profile, int(task.segment_frame_count or 0), preserve_audio=True)
		c._validate_normalized_video(output, profile, expected_frames=frames)
		content = output.read_bytes()
	manifest = dict(
		method="Explicitly retained held inference for review",
		original_run=run.name,
		original_attempt=attempt.name,
		source_sha256=content_hash,
		output_sha256=digest(content),
		machine_status=report["status"],
		machine_policy=report.get("policy"),
		machine_findings=report["results"],
		original_machine_status=(original_report or {}).get("status"),
		original_machine_findings=(original_report or {}).get("results", []),
		supplementary_review=review_artifact,
		retained_by=frappe.session.user,
		retained_at=str(frappe.utils.now_datetime()),
		review_note=review_note.strip(),
	)
	version = c._persist_composed_output(
		run.name,
		shot.name,
		asset.name,
		artifact,
		content,
		frames / profile["fps"],
		profile["fps"],
		select_output=False,
		can_select=False,
		review_manifest=manifest,
		retained_review=True,
	)
	return dict(asset_version=version, selected=False, status="Review Required")


@frappe.whitelist()
def use_reviewed_take(project_name, shot_name, asset_version, expected_current):
	"""Select a reviewed immutable candidate, guarded against stale history tabs."""
	project, shot = _project_shot(project_name, shot_name)
	selected = frappe.db.sql(
		"select selected_output_asset_version from `tabShot` where name=%s for update", shot.name
	)[0][0]
	if (selected or "") != (expected_current or ""):
		frappe.throw(_("The selected take changed. Reload the scene history."))
	names = [row.name for row in scene_takes(project.name, shot.name)]
	if asset_version not in names:
		frappe.throw(_("Choose a take from this scene."), frappe.PermissionError)
	return select_scene_take(project.name, shot.name, names.index(asset_version) + 1)
