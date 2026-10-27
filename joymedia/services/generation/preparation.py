"""Preparing a Generation Run: validate the project and workflow, plan each scene's segments and pipeline steps, and create the tasks, attempts and inputs."""

import hashlib
import json

import frappe
from frappe import _

from joymedia.services.generation.run_state import (
	ACTIVE_RUN_STATUSES,
	_enqueue_submit_run,
	_exception_message,
	_raise_run_error,
	_refresh_run_counters,
	_run_summary,
)
from joymedia.services.generation.runner import (
	prepare_generation_task,
)
from joymedia.services.generation.segments import plan_generation_segments
from joymedia.services.planning.prompts import (
	compile_segment_prompt_from_snapshot,
	prompt_source_for_workflow,
)
from joymedia.services.workflows.capabilities import capacity, controls
from joymedia.services.workflows.pipeline import get_pipeline_steps
from joymedia.services.workflows.profiles import (
	choose_shot_workflow,
	input_role_for_workflow,
	references_for_workflow,
)
from joymedia.services.workflows.resolver import (
	validate_role_input_count,
	validate_workflow_bindings,
	validate_workflow_for_execution,
	workflow_supports_continuation,
)


def _prompt_shot(shot_name, shot):
	"""Keep the same frozen scene fields in image-pipeline and direct tasks."""
	return frappe._dict(
		name=shot_name,
		shot_number=shot.get("shot_number"),
		generation_prompt=shot.get("generation_prompt"),
		duration_seconds=shot.get("duration_seconds"),
		image_prompt=shot.get("image_prompt"),
		keyframe_retry_note=shot.get("keyframe_retry_note"),
		keyframe_artifact=shot.get("keyframe_artifact"),
		setting_prompt=shot.get("setting_prompt"),
		character_mode=shot.get("character_mode"),
		views_json=shot.get("views_json"),
		motion_plan_json=shot.get("motion_plan_json"),
		start_state=shot.get("start_state"),
		end_state=shot.get("end_state"),
		handoff_type=shot.get("handoff_type"),
		continuity_mode=shot.get("continuity_mode"),
		references=shot.get("references") or [],
	)


def _continuation_settings(workflow):
	"""Read segment behavior from the immutable workflow contract, not model code."""
	try:
		spec = frappe.parse_json(workflow.execution_spec or "{}")
	except (TypeError, ValueError):
		spec = {}
	settings = spec.get("continuation") or {}
	return {
		"overlap_frames": max(0, int(settings.get("overlap_frames", 1))),
		"new_frames": settings.get("new_frames"),
	}


def _continuation_workflow(workflow):
	return (
		frappe.get_doc("Generation Workflow", workflow.continuation_workflow)
		if workflow.continuation_workflow
		else None
	)


def _segment_plan(workflow, frame_count, continuation_workflow=None):
	settings = _continuation_settings(workflow)
	segments = plan_generation_segments(
		frame_count,
		max_segment_frames=capacity(workflow),
		continuation_overlap_frames=settings["overlap_frames"],
		continuation_new_frames=settings["new_frames"],
		continuation_max_segment_frames=capacity(continuation_workflow or workflow),
	)
	if len(segments) > 1 and not (
		continuation_workflow and workflow_supports_continuation(continuation_workflow)
	):
		frappe.throw(
			_("This shot exceeds the workflow capacity, and its workflow has no continuation contract.")
		)
	return segments


def _pipeline_reference_inputs(shot, workflow):
	"""Map a Shot's ordered references into the pipeline's first image stage."""
	from joymedia.services.keyframes.overlay import DRAW, pasted_references, scene_mode
	from joymedia.services.workflows.resolver import get_workflow_input_contract
	from joymedia.services.workflows.routing import normalize_reference_role

	character_mode = (shot.get("character_mode") if hasattr(shot, "get") else None) or DRAW
	contract = get_workflow_input_contract(workflow)
	roles = {item["role"] for item in contract if item.get("role")}
	role_limits = {
		item["role"]: item.get("max_count")
		for item in contract
		if item.get("role") and item.get("max_count") is not None
	}
	image_role = next(
		(
			item["role"]
			for item in contract
			if item.get("accepted_media_type") in ("Image", "Any") and item.get("allow_multiple")
		),
		"first_frame",
	)
	from joymedia.services.scene.artwork import placements

	auto_place = bool(shot.get("reference_retention") and not placements(shot.get("motion_plan_json")))
	inputs = {}
	for reference in shot.get("references") or []:
		asset_version = reference.get("asset_version")
		if not asset_version:
			continue
		raw_role = frappe.scrub(reference.get("input_role") or reference.get("reference_role") or "")
		# A last frame is a destination constraint for the video stage.  It is
		# never a visual reference for the keyframe/image stage.
		if raw_role == "last_frame" or (
			raw_role == "first_frame" and getattr(workflow, "output_media_type", None) == "Image"
		):
			continue
		if raw_role == "logo" or (
			pasted_references([reference], character_mode, context=shot.get("references"))
			and not (auto_place and raw_role == "product")
		):
			# A cutout is pasted over the keyframe and a logo over the film.  An opaque
			# product cannot be composited without also pasting its background, so it
			# must remain in the image workflow's dedicated product input.  Dropping it
			# here makes the model invent packaging instead of receiving the approved
			# reference at all.
			continue
		if (
			scene_mode(shot.get("references"), character_mode) == DRAW
			and raw_role in ("character", "product")
			and len(inputs.get(raw_role) or []) >= max(1, role_limits.get(raw_role) or 1)
		):
			# As many pictures go in per role as the workflow has slots for; with more, every character (and every
			# product) of the scene is combined into one board (the runner's boards_for_task).
			continue
		# Keep an already-concrete workflow role intact.  In particular, direct
		# R2V uses ``product_reference`` for two scalar image slots; converting it
		# to a semantic routing alias here leaves the required slots unbound.
		role = raw_role if raw_role in roles else normalize_reference_role(raw_role)
		if role not in roles:
			role = image_role
		values = inputs.setdefault(role, [])
		max_count = role_limits.get(role)
		# The workflow contract uses zero for an unbounded File Paths role.
		if max_count and len(values) >= max_count:
			frappe.throw(
				_(
					"Workflow {0} accepts at most {1} reference input(s) for role '{2}', but Shot supplies more. "
					"Assign a supported reference board or remove the extra reference explicitly."
				).format(workflow.name, max_count, role)
			)
		values.append(asset_version)
	return inputs


def explicit_last_frame_assets(shot):
	"""Return user-selected endpoint images, never an automatically invented anchor."""
	assets = []
	for reference in shot.get("references") or []:
		role = frappe.scrub(reference.get("input_role") or reference.get("reference_role") or "")
		asset_version = reference.get("asset_version")
		if role == "last_frame" and asset_version and asset_version not in assets:
			assets.append(asset_version)
	return assets


def authored_video_inputs(shot, workflow):
	"""Bind execution controls to declared video roles; keep cast references for review."""
	from joymedia.services.workflows.resolver import get_workflow_input_contract

	contract = get_workflow_input_contract(workflow)
	roles = {item["role"] for item in contract}
	inputs = {}
	for row in shot.get("references") or []:
		role = frappe.scrub(row.get("input_role") or row.get("reference_role") or "")
		if role in roles and role != "last_frame" and row.get("asset_version"):
			inputs.setdefault(role, []).append(row["asset_version"])
	if len(inputs.get("first_frame", [])) != 1:
		raise ValueError("The video workflow must accept exactly one authored first frame.")
	for item in contract:
		role = item["role"]
		if role == "last_frame":
			continue
		if item.get("required") and not inputs.get(role):
			raise ValueError(f"The video workflow requires an explicit '{role}' input.")
		if inputs.get(role):
			validate_role_input_count(workflow, role, len(inputs[role]))
	return inputs


def video_reference_inputs(shot, workflow):
	"""Forward only declared reference roles; upstream artifacts own frame controls.

	A later video stage may condition on the original product as well as its
	generated opening frame. Never infer a reference binding or replace a chained
	first/last frame with a static source image.
	"""
	from joymedia.services.workflows.resolver import get_workflow_input_contract

	contract = get_workflow_input_contract(workflow)
	roles = {item["role"] for item in contract} - {"first_frame", "last_frame"}
	inputs = {}
	for row in shot.get("references") or []:
		role = frappe.scrub(row.get("input_role") or row.get("reference_role") or "")
		asset = row.get("asset_version")
		if role in roles and asset and asset not in inputs.setdefault(role, []):
			inputs[role].append(asset)
	for role, assets in inputs.items():
		validate_role_input_count(workflow, role, len(assets))
	for item in contract:
		if item["role"] in roles and item.get("required") and not inputs.get(item["role"]):
			raise ValueError(f"The video workflow requires an explicit '{item['role']}' reference.")
	return inputs


def _bind_explicit_last_frame(job, workflow, shot):
	"""Bind an approved destination only when the selected video graph supports it."""
	from joymedia.services.workflows.resolver import get_workflow_input_contract

	assets = explicit_last_frame_assets(shot)
	if not assets:
		return
	contract = {item.get("role"): item for item in get_workflow_input_contract(workflow)}
	if "last_frame" not in contract:
		frappe.throw(
			_("Shot requests a last frame, but workflow {0} has no last-frame input.").format(workflow.name)
		)
	max_count = int(contract["last_frame"].get("max_count") or 1)
	if max_count and len(assets) > max_count:
		frappe.throw(
			_("Shot supplies more last-frame images than workflow {0} accepts.").format(workflow.name)
		)
	for asset_version in assets:
		job.append("inputs", {"input_role": "last_frame", "asset_version": asset_version})


def _pipeline_steps_for_segment(
	pipeline_steps,
	*,
	previous_segment_job=None,
	previous_shot_tail_job=None,
	cross_shot_continuity=False,
	force_full_pipeline=False,
	keyframe_job=None,
	explicit_first_frame=False,
	reference_only=False,
):
	"""Return executable stages, chaining later continuous segments from Last Frame.

	The first segment/shot runs the full configured pipeline (for example, a
	keyframe workflow followed by I2V). A later segment or continuous shot already
	has its visual start state, so it runs only the final pipeline stage with the
	upstream video's Last Frame bound dynamically as that workflow's first frame.
	"""
	if not pipeline_steps:
		return []
	if reference_only:
		return [(pipeline_steps[-1], None, None, True)]
	if (
		explicit_first_frame
		and not previous_segment_job
		and not (cross_shot_continuity and previous_shot_tail_job)
	):
		# An authored image is already the visual start state. Bind the immutable
		# Asset Version instead of drawing a replacement in the image stage.
		return [(pipeline_steps[-1], None, None, True)]
	if keyframe_job and not previous_segment_job:
		# The scene's approved keyframe replaces the pipeline's image stage.
		return [(pipeline_steps[-1], keyframe_job, "Primary Image", False)]
	continuation_source = (
		None
		if force_full_pipeline
		else (previous_segment_job or (previous_shot_tail_job if cross_shot_continuity else None))
	)
	if continuation_source:
		return [(pipeline_steps[-1], continuation_source, "Last Frame", False)]

	return [(step, None, None, index == 0) for index, step in enumerate(pipeline_steps)]


def prepare_run(run_name: str):
	"""Retry task construction from a fresh transaction after an InnoDB conflict.

	Preparation only freezes database inputs; it never submits a GPU prompt. A
	rolled-back preparation can therefore be retried without duplicating renders.
	"""
	from frappe.utils.synchronization import filelock

	with filelock(f"joymedia-prepare-run-{run_name}"):
		for attempt in range(3):
			try:
				return _prepare_run(run_name)
			except frappe.QueryDeadlockError:
				frappe.db.rollback()
				if attempt == 2:
					raise


def _prepare_run(run_name: str):
	"""Create one Generation Task and frozen Generation Input snapshot for each Shot in a run."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status == "Cancelled":
		return _run_summary(run)
	if run.status not in ACTIVE_RUN_STATUSES:
		frappe.throw(_("Generation Run {0} cannot be prepared from status {1}.").format(run.name, run.status))

	project = frappe.get_doc("Media Project", run.media_project)
	try:
		snapshot = frappe.parse_json(run.project_snapshot_json or "{}")
	except (TypeError, ValueError):
		_raise_run_error(run, _("Generation Run {0} has invalid project snapshot JSON.").format(run.name))
		return _run_summary(run)
	if snapshot.get("media_project") != run.media_project:
		_raise_run_error(
			run, _("Generation Run {0} snapshot belongs to another Media Project.").format(run.name)
		)
		return _run_summary(run)
	workflow = frappe.get_doc(
		"Generation Workflow",
		run.workflow,
	)
	continuation_workflow = _continuation_workflow(workflow)
	shots = snapshot.get("shots") or []
	try:
		execution_scope = frappe.parse_json(run.execution_scope_json or "{}")
		execution_scope = execution_scope if isinstance(execution_scope, dict) else {}
	except (TypeError, ValueError):
		_raise_run_error(run, _("Generation Run {0} has invalid execution scope JSON.").format(run.name))
		return _run_summary(run)
	shot_names = set(execution_scope.get("shot_names") or [])
	if shot_names:
		shots = [shot for shot in shots if shot.get("shot") in shot_names]
	if not shots:
		_raise_run_error(run, _("Media Project {0} has no Shots.").format(project.name))
		return _run_summary(run)

	try:
		validate_workflow_for_execution(workflow)
		validate_workflow_bindings(workflow)
		if continuation_workflow:
			validate_workflow_for_execution(continuation_workflow)
			validate_workflow_bindings(continuation_workflow)
		# Continuity is an editorial decision on the destination Shot.  A project
		# mode may influence planning, but must never override an explicit scene
		# reset or continuation instruction.
		cross_shot_continuity = False
		jobs_to_prepare = []
		previous_shot_tail_job = execution_scope.get("continuation_from_task")
		keyframe_stage = execution_scope.get("stage") == "keyframe"
		for shot in shots:
			from joymedia.services.planning.shot_structure import require_scene_references

			require_scene_references(snapshot, shot)
			from joymedia.services.review.admission import needs_frame_approval

			shot_workflow = choose_shot_workflow(snapshot, shot)
			if needs_frame_approval(
				snapshot, shot, keyframe_stage, reference_only="reference_only" in controls(shot_workflow)
			):
				raise frappe.ValidationError(
					_("Review and approve this scene's first frame before animating its geometry.")
				)
			cross_shot_continuity = str(shot.get("continuity_mode") or "").casefold() == "continue"
			shot_name = shot.get("shot")
			shot_pipeline_name = shot.get("generation_pipeline") or run.generation_pipeline
			shot_pipeline_steps = get_pipeline_steps(shot_pipeline_name) if shot_pipeline_name else []
			if shot_pipeline_steps and shot_pipeline_steps[-1].workflow != shot_workflow.name:
				raise frappe.ValidationError(
					_("Shot {0} pipeline does not end with its routed workflow.").format(shot_name)
				)
			for pipeline_step in shot_pipeline_steps:
				pipeline_workflow = frappe.get_doc("Generation Workflow", pipeline_step.workflow)
				validate_workflow_for_execution(pipeline_workflow)
				validate_workflow_bindings(pipeline_workflow)
			shot_continuation_workflow = _continuation_workflow(shot_workflow)
			validate_workflow_for_execution(shot_workflow)
			validate_workflow_bindings(shot_workflow)
			if shot_continuation_workflow:
				validate_workflow_for_execution(shot_continuation_workflow)
				validate_workflow_bindings(shot_continuation_workflow)
			segments = _segment_plan(
				shot_workflow, shot.get("planned_frame_count"), shot_continuation_workflow
			)
			previous_segment_job = None
			for segment in segments[:1] if keyframe_stage else segments:
				if shot_pipeline_steps:
					explicit_frames = [
						r["asset_version"]
						for r in shot.get("references") or []
						if frappe.scrub(r.get("reference_role") or r.get("input_role") or "") == "first_frame"
						and r.get("asset_version")
					]
					if len(explicit_frames) > 1:
						raise ValueError("Choose one explicit first frame for a scene.")
					previous_pipeline_job = None
					pipeline_stages = _pipeline_steps_for_segment(
						shot_pipeline_steps,
						previous_segment_job=previous_segment_job,
						previous_shot_tail_job=previous_shot_tail_job,
						cross_shot_continuity=cross_shot_continuity,
						# A scene reset needs a fresh keyframe only for its first
						# technical segment. Later segments must use the prior last frame when the workflow supports it.
						force_full_pipeline=bool(shot.get("requires_recomposition"))
						and segment["segment_index"] == 1,
						keyframe_job=None if keyframe_stage else shot.get("keyframe_task"),
						explicit_first_frame=bool(explicit_frames) and not keyframe_stage,
						reference_only=not keyframe_stage and "reference_only" in controls(shot_workflow),
					)
					if keyframe_stage:
						pipeline_stages = pipeline_stages[:1]
					for (
						pipeline_step,
						dependency_override,
						artifact_role_override,
						is_first_pipeline_step,
					) in pipeline_stages:
						step_workflow = frappe.get_doc("Generation Workflow", pipeline_step.workflow)
						existing_job = frappe.db.get_value(
							"Generation Task",
							{
								"generation_run": run.name,
								"shot": shot_name,
								"segment_index": segment["segment_index"],
								"pipeline_step_key": pipeline_step.step_key,
							},
							"name",
						)
						if existing_job:
							previous_pipeline_job = existing_job
							continue
						prompt_text = compile_segment_prompt_from_snapshot(
							_prompt_shot(shot_name, shot),
							frappe._dict(snapshot),
							segment["segment_index"],
							len(segments),
							prompt_source=prompt_source_for_workflow(
								step_workflow, pipeline_step.prompt_source
							),
							is_final=(
								shot.get("shot_number") == len(snapshot.get("shots") or [])
								and segment["segment_index"] == len(segments)
							),
							segment_start_frame=segment["segment_start_frame"],
							segment_effective_frames=segment["segment_effective_frames"],
							fps=snapshot.get("output_fps") or 24,
							workflow=step_workflow,
						)
						job = frappe.get_doc(
							{
								"doctype": "Generation Task",
								"generation_run": run.name,
								"shot": shot_name,
								"workflow": pipeline_step.workflow,
								"pipeline_step_key": pipeline_step.step_key,
								"prompt_text": prompt_text,
								"prompt_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
								"status": "Draft",
								"segment_index": segment["segment_index"],
								"segment_frame_count": (
									segment["segment_frame_count"]
									if step_workflow.output_media_type == "Video"
									else max(1, int(step_workflow.frame_count or 1))
								),
								"segment_start_frame": segment["segment_start_frame"],
								"segment_effective_frames": (
									segment["segment_effective_frames"]
									if step_workflow.output_media_type == "Video"
									else max(1, int(step_workflow.frame_count or 1))
								),
								"overlap_frames": segment["overlap_frames"]
								if step_workflow.output_media_type == "Video"
								else 0,
								"depends_on_task": dependency_override or previous_pipeline_job,
								"dependency_artifact_role": (
									artifact_role_override
									or (
										pipeline_step.consumes_artifact_role
										if previous_pipeline_job
										else None
									)
								),
							}
						).insert(ignore_permissions=True)
						if step_workflow.output_media_type == "Video":
							_bind_explicit_last_frame(job, step_workflow, shot)
						# Later video stages keep the upstream opening artifact AND any
						# original references explicitly declared by that workflow.
						if is_first_pipeline_step:
							if "reference_only" in controls(step_workflow) and not keyframe_stage:
								inputs = video_reference_inputs(shot, step_workflow)
							elif (
								explicit_frames
								and not keyframe_stage
								and step_workflow.output_media_type == "Video"
							):
								inputs = authored_video_inputs(shot, step_workflow)
							else:
								inputs = _pipeline_reference_inputs(shot, step_workflow)
						else:
							inputs = (
								video_reference_inputs(shot, step_workflow)
								if step_workflow.output_media_type == "Video"
								else {}
							)
						for input_role, asset_versions in inputs.items():
							for asset_version in asset_versions:
								job.append(
									"inputs", {"input_role": input_role, "asset_version": asset_version}
								)
						job.save(ignore_permissions=True)
						jobs_to_prepare.append(job)
						previous_pipeline_job = job.name
					previous_segment_job = previous_pipeline_job
					previous_shot_tail_job = previous_pipeline_job
					continue
				existing_job = frappe.db.get_value(
					"Generation Task",
					{
						"generation_run": run.name,
						"shot": shot_name,
						"segment_index": segment["segment_index"],
					},
					"name",
				)
				if existing_job:
					previous_segment_job = existing_job
					continue

				dependency = previous_segment_job
				if (
					not dependency
					and cross_shot_continuity
					and previous_shot_tail_job
					and not shot.get("requires_recomposition")
				):
					dependency = previous_shot_tail_job
				segment_workflow = (
					shot_continuation_workflow
					if shot_continuation_workflow
					and (
						segment["segment_index"] > 1 or (dependency and dependency == previous_shot_tail_job)
					)
					else shot_workflow
				)
				prompt_text = compile_segment_prompt_from_snapshot(
					_prompt_shot(shot_name, shot),
					frappe._dict(snapshot),
					segment["segment_index"],
					len(segments),
					prompt_source=prompt_source_for_workflow(segment_workflow),
					is_final=(
						shot.get("shot_number") == len(snapshot.get("shots") or [])
						and segment["segment_index"] == len(segments)
					),
					segment_start_frame=segment["segment_start_frame"],
					segment_effective_frames=segment["segment_effective_frames"],
					fps=snapshot.get("output_fps") or 24,
					workflow=segment_workflow,
				)
				job = frappe.get_doc(
					{
						"doctype": "Generation Task",
						"generation_run": run.name,
						"shot": shot_name,
						"workflow": segment_workflow.name,
						"prompt_text": prompt_text,
						"prompt_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
						"status": "Draft",
						"segment_index": segment["segment_index"],
						"segment_frame_count": segment["segment_frame_count"],
						"segment_start_frame": segment["segment_start_frame"],
						"segment_effective_frames": segment["segment_effective_frames"],
						"overlap_frames": segment["overlap_frames"],
						"depends_on_task": dependency,
					}
				).insert(ignore_permissions=True)
				job.set(
					"inputs",
					[
						{
							"input_role": input_role_for_workflow(shot_workflow),
							"asset_version": reference.get("asset_version"),
						}
						for reference in references_for_workflow(shot_workflow, shot.get("references"))
						if reference.get("reference_role") and reference.get("asset_version")
					],
				)
				job.save(ignore_permissions=True)
				jobs_to_prepare.append(job)
				previous_segment_job = job.name
			previous_shot_tail_job = previous_segment_job

		for job in jobs_to_prepare:
			if job.pipeline_step_key:
				pipeline_snapshot = [
					{"reference_role": row.input_role, "asset_version": row.asset_version}
					for row in job.get("inputs") or []
					if row.asset_version
				]
				prepare_generation_task(job.name, pipeline_snapshot)
				continue
			shot_snapshot = next(
				(item for item in shots if item.get("shot") == job.shot),
				{"references": []},
			)
			# The role comes from the take's starting workflow: a reference take's
			# continuations keep its reference images, while an image-to-video
			# chain's first frame is replaced by the previous segment's last frame.
			shot_role = input_role_for_workflow(choose_shot_workflow(snapshot, shot_snapshot))
			prepare_snapshot = [
				{
					**reference,
					"reference_role": shot_role,
				}
				for reference in references_for_workflow(
					choose_shot_workflow(snapshot, shot_snapshot), shot_snapshot.get("references")
				)
			]
			prepare_generation_task(job.name, prepare_snapshot)
	except frappe.QueryDeadlockError:
		raise
	except Exception as exc:
		_raise_run_error(run, _exception_message(exc))
		return _run_summary(run)

	_refresh_run_counters(run)
	_enqueue_submit_run(run.name)
	return _run_summary(run)


def validate_generation_preflight(project, workflow, shots, *, check_comfyui=False, execution_scope=None):
	if (execution_scope or {}).get("stage") != "keyframe":
		from joymedia.services.keyframes.product_review import assert_product_frame_ready

		for shot_row in shots:
			assert_product_frame_ready(project, frappe.get_doc("Shot", shot_row.name))
	if not frappe.conf.get("comfyui_base_url"):
		frappe.throw(_("comfyui_base_url is not configured."))
	object_info = None
	if check_comfyui:
		from joymedia.services.workflows.comfyui import get_object_info, get_system_stats

		get_system_stats()
		object_info = get_object_info()

	from joymedia.services.project.context import build_project_snapshot
	from joymedia.services.workflows.profiles import choose_shot_workflow

	try:
		snapshot = json.loads(build_project_snapshot(project, require_production_pipeline=True)[0])
	except (TypeError, ValueError):
		frappe.throw(_("The project snapshot could not be prepared for preflight."))
	snapshot_shots = {row.get("shot"): row for row in snapshot.get("shots") or []}
	if not snapshot.get("generation_pipeline"):
		frappe.throw(_("Generation requires an explicitly promoted Generation Pipeline."))

	for shot_row in shots:
		shot = frappe.get_doc("Shot", shot_row.name)
		shot_snapshot = snapshot_shots.get(
			shot.name,
			{
				"shot": shot.name,
				"shot_number": shot.shot_number,
				"planned_frame_count": shot.planned_frame_count,
				"generation_prompt": shot.generation_prompt,
				"references": [
					{"reference_role": row.reference_role, "asset_version": row.asset_version}
					for row in shot.generation_inputs or []
				],
			},
		)
		shot_workflow = choose_shot_workflow(snapshot, shot_snapshot)
		shot_pipeline_name = shot_snapshot.get("generation_pipeline")
		shot_pipeline = (
			frappe.get_doc("Generation Pipeline", shot_pipeline_name) if shot_pipeline_name else None
		)
		pipeline_steps = get_pipeline_steps(shot_pipeline.name) if shot_pipeline else []
		validate_workflow_for_execution(shot_workflow)
		validate_workflow_bindings(shot_workflow)
		if object_info is not None:
			from joymedia.services.workflows.resolver import validate_workflow_node_types_available

			validate_workflow_node_types_available(shot_workflow, object_info)
		for pipeline_step in pipeline_steps:
			pipeline_workflow = frappe.get_doc("Generation Workflow", pipeline_step.workflow)
			validate_workflow_for_execution(pipeline_workflow)
			validate_workflow_bindings(pipeline_workflow)
			if pipeline_workflow.output_media_type == "Video":
				video_reference_inputs(shot_snapshot, pipeline_workflow)
			if object_info is not None:
				validate_workflow_node_types_available(pipeline_workflow, object_info)
		continuation_workflow = _continuation_workflow(shot_workflow)
		if continuation_workflow:
			validate_workflow_for_execution(continuation_workflow)
			validate_workflow_bindings(continuation_workflow)
		input_workflow = (
			frappe.get_doc("Generation Workflow", pipeline_steps[0].workflow)
			if pipeline_steps
			else shot_workflow
		)
		required_roles = {
			frappe.scrub(binding.required_input_role)
			for binding in input_workflow.bindings
			if binding.required and binding.required_input_role
		}
		if not (shot.generation_prompt or "").strip():
			frappe.throw(
				_("Shot {0} has no generation prompt. Regenerate or edit the storyboard first.").format(
					shot.name
				)
			)

		# Match the exact binding behaviour used when the Generation Task is
		# prepared.  This also lets an older multi-reference storyboard fall back
		# to its first image when the optional Ref2V backend is not installed.
		mappings = _pipeline_reference_inputs(
			frappe._dict(references=shot_snapshot.get("references") or []), input_workflow
		)
		for role in required_roles:
			if pipeline_steps and role == "first_frame":
				# The pipeline's upstream image workflow creates this input.
				continue
			if (
				role == "first_frame"
				and shot_row.shot_number > 1
				and (
					project.generation_mode in ("Continuous", "Consistency")
					or (execution_scope or {}).get("continuity")
					or (execution_scope or {}).get("continuation_from_task")
				)
			):
				continue
			asset_versions = mappings.get(role, [])
			if not asset_versions or any(
				not frappe.db.get_value("Asset Version", asset_version, "file")
				for asset_version in asset_versions
			):
				frappe.throw(_("Shot {0} requires usable input(s) with role '{1}'.").format(shot.name, role))
			validate_role_input_count(input_workflow, role, len(asset_versions))

		segments = _segment_plan(shot_workflow, shot_row.planned_frame_count, continuation_workflow)
		if not segments:
			frappe.throw(_("Shot {0} has no generation segments.").format(shot.name))
		continuation_capacity = (continuation_workflow or shot_workflow).frame_count
		if segments[0]["segment_frame_count"] > shot_workflow.frame_count or any(
			segment["segment_frame_count"] > continuation_capacity for segment in segments[1:]
		):
			frappe.throw(
				_("Shot {0} contains a segment larger than Workflow frame capacity.").format(shot.name)
			)
