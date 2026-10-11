import hashlib
import json
import secrets

import frappe
from frappe import _
from frappe.utils.synchronization import filelock
from frappe.utils import now

from joymedia.joymedia.doctype.generation_attempt.generation_attempt import (
	create_retry_attempt_internal,
	get_effective_attempt_from_history,
)

from .generation_runner import (
	attach_chained_first_frame,
	ensure_generation_inputs,
	prepare_generation_task,
	submit_attempt,
)
from .generation_segment_planner import plan_generation_segments
from .generation_pipeline_service import get_pipeline_steps, pipeline_for_final_workflow
from .prompt_compiler import compile_segment_prompt_from_snapshot, prompt_source_for_workflow
from .result_ingestor import sync_attempt_result
from .video_composer import compose_shot_segments
from .workflow_profiles import choose_shot_workflow, input_role_for_workflow, references_for_workflow
from .workflow_resolver import (
	validate_role_input_count,
	validate_workflow_bindings,
	validate_workflow_for_execution,
	workflow_supports_continuation,
)


ACTIVE_RUN_STATUSES = ("Queued", "Running")
ACTIVE_ATTEMPT_STATUSES = ("Pending", "Submitting", "Queued", "Running")
TERMINAL_ATTEMPT_STATUSES = ("Completed", "Failed", "Cancelled")
TERMINAL_JOB_STATUSES = ("Completed", "Failed", "Cancelled")
MAX_AUTOMATIC_RETRIES = 1
# Keep each generation run strictly ordered.  This is required for chained
# shots: the next shot must not enter ComfyUI until the previous shot has
# produced the Last Frame artifact used as its first frame.
MAX_JOBS_IN_FLIGHT_PER_RUN = 1


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
	return frappe.get_doc("Generation Workflow", workflow.continuation_workflow) if workflow.continuation_workflow else None


def _segment_plan(workflow, frame_count, continuation_workflow=None):
	settings = _continuation_settings(workflow)
	segments = plan_generation_segments(
		frame_count,
		max_segment_frames=workflow.frame_count,
		continuation_overlap_frames=settings["overlap_frames"],
		continuation_new_frames=settings["new_frames"],
		continuation_max_segment_frames=int(
			getattr(continuation_workflow, "frame_count", None) or workflow.frame_count
		),
	)
	if len(segments) > 1 and not (continuation_workflow and workflow_supports_continuation(continuation_workflow)):
		frappe.throw(_("This shot exceeds the workflow capacity, and its workflow has no continuation contract."))
	return segments


def _pipeline_reference_inputs(shot, workflow):
	"""Map a Shot's ordered references into the pipeline's first image stage."""
	from .workflow_resolver import get_workflow_input_contract
	from .reference_compositor import normalize_reference_role

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
			if item.get("accepted_media_type") in ("Image", "Any")
			and item.get("allow_multiple")
		),
		"first_frame",
	)
	inputs = {}
	for reference in shot.get("references") or []:
		asset_version = reference.get("asset_version")
		if not asset_version:
			continue
		role = normalize_reference_role(reference.get("input_role") or reference.get("reference_role") or "")
		if role not in roles:
			role = image_role
		values = inputs.setdefault(role, [])
		max_count = role_limits.get(role)
		# The workflow contract uses zero for an unbounded File Paths role.
		if not max_count or len(values) < max_count:
			values.append(asset_version)
	return inputs


def _pipeline_steps_for_segment(
	pipeline_steps,
	*,
	previous_segment_job=None,
	previous_shot_tail_job=None,
	cross_shot_continuity=False,
):
	"""Return executable stages, chaining later continuous segments from Last Frame.

	The first segment/shot runs the full configured pipeline (for example, a
	keyframe workflow followed by I2V). A later segment or continuous shot already
	has its visual start state, so it runs only the final pipeline stage with the
	upstream video's Last Frame bound dynamically as that workflow's first frame.
	"""
	if not pipeline_steps:
		return []
	continuation_source = previous_segment_job or (
		previous_shot_tail_job if cross_shot_continuity else None
	)
	if continuation_source:
		return [(pipeline_steps[-1], continuation_source, "Last Frame", False)]

	return [(step, None, None, index == 0) for index, step in enumerate(pipeline_steps)]


@frappe.whitelist()
def start_run(run_name: str):
	"""Start a Draft Generation Run and hand the remaining workflow to background jobs."""
	frappe.has_permission("Generation Run", "write", run_name, throw=True)
	return start_run_internal(run_name)


def start_run_internal(run_name: str):
	"""Start a run after the caller has authorized its owning Campaign."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status != "Draft":
		frappe.throw(_("Generation Run {0} must be Draft to start.").format(run.name))

	project = frappe.get_doc("Media Project", run.media_project)
	if not project.workflow:
		frappe.throw(_("Media Project {0} has no Generation Workflow.").format(project.name))

	workflow = frappe.get_doc("Generation Workflow", run.workflow)
	try:
		execution_scope = frappe.parse_json(run.execution_scope_json or "{}")
		execution_scope = execution_scope if isinstance(execution_scope, dict) else {}
	except (TypeError, ValueError):
		frappe.throw(_("Generation Run {0} has invalid execution scope JSON.").format(run.name))
	shots = frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		fields=["name", "shot_number", "planned_frame_count"],
		order_by="shot_number asc, name asc",
	)
	shot_names = set(execution_scope.get("shot_names") or [])
	if shot_names:
		shots = [shot for shot in shots if shot.name in shot_names]
	if shot_names and not shots:
		frappe.throw(_("Generation Run {0} has no Shots in its execution scope.").format(run.name))
	preflight_kwargs = {"check_comfyui": True}
	if execution_scope:
		preflight_kwargs["execution_scope"] = execution_scope
	validate_generation_preflight(project, workflow, shots, **preflight_kwargs)

	run.status = "Queued"
	run.error_summary = None
	run.db_set(
		{"status": run.status, "error_summary": run.error_summary},
		update_modified=False,
	)
	frappe.db.set_value("Media Project", project.name, "status", "Generating", update_modified=False)
	_enqueue("prepare_run", run.name)
	return {"name": run.name, "status": run.status}


def prepare_run(run_name: str):
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
		_raise_run_error(run, _("Generation Run {0} snapshot belongs to another Media Project.").format(run.name))
		return _run_summary(run)
	workflow = frappe.get_doc(
		"Generation Workflow",
		run.workflow,
	)
	pipeline_steps = get_pipeline_steps(run.generation_pipeline) if run.generation_pipeline else []
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
		for pipeline_step in pipeline_steps:
			pipeline_workflow = frappe.get_doc("Generation Workflow", pipeline_step.workflow)
			validate_workflow_for_execution(pipeline_workflow)
			validate_workflow_bindings(pipeline_workflow)
		if continuation_workflow:
			validate_workflow_for_execution(continuation_workflow)
			validate_workflow_bindings(continuation_workflow)
		cross_shot_continuity = bool(
			snapshot.get("generation_mode") in ("Continuous", "Consistency")
			or execution_scope.get("continuity")
		)
		jobs_to_prepare = []
		previous_shot_tail_job = (
			execution_scope.get("continuation_from_task") if cross_shot_continuity else None
		)
		for shot in shots:
			shot_name = shot.get("shot")
			shot_workflow = choose_shot_workflow(snapshot, shot)
			shot_pipeline_steps = pipeline_steps if pipeline_steps and pipeline_steps[-1].workflow == shot_workflow.name else []
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
			for segment in segments:
				if shot_pipeline_steps:
					previous_pipeline_job = None
					pipeline_stages = _pipeline_steps_for_segment(
						shot_pipeline_steps,
						previous_segment_job=previous_segment_job,
						previous_shot_tail_job=previous_shot_tail_job,
						cross_shot_continuity=cross_shot_continuity,
					)
					for pipeline_step, dependency_override, artifact_role_override, is_first_pipeline_step in pipeline_stages:
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
							frappe._dict(
								name=shot_name, shot_number=shot.get("shot_number"),
								generation_prompt=shot.get("generation_prompt"),
								image_prompt=shot.get("image_prompt"),
								motion_plan_json=shot.get("motion_plan_json"),
								start_state=shot.get("start_state"), end_state=shot.get("end_state"),
								handoff_type=shot.get("handoff_type"),
							),
							frappe._dict(snapshot), segment["segment_index"], len(segments),
							prompt_source=prompt_source_for_workflow(step_workflow, pipeline_step.prompt_source),
							is_final=shot.get("shot_number") == len(snapshot.get("shots") or []),
						)
						job = frappe.get_doc({
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
								if step_workflow.output_media_type == "Video" else max(1, int(step_workflow.frame_count or 1))
							),
							"segment_start_frame": segment["segment_start_frame"],
							"segment_effective_frames": (
								segment["segment_effective_frames"]
								if step_workflow.output_media_type == "Video" else max(1, int(step_workflow.frame_count or 1))
							),
							"overlap_frames": segment["overlap_frames"] if step_workflow.output_media_type == "Video" else 0,
							"depends_on_task": dependency_override or previous_pipeline_job,
							"dependency_artifact_role": (
								artifact_role_override
								or (pipeline_step.consumes_artifact_role if previous_pipeline_job else None)
							),
						}).insert(ignore_permissions=True)
						# The first pipeline stage consumes the Shot's ordered references;
						# later stages consume only the upstream generated artifact.
						if is_first_pipeline_step:
							for input_role, asset_versions in _pipeline_reference_inputs(shot, step_workflow).items():
								for asset_version in asset_versions:
									job.append("inputs", {"input_role": input_role, "asset_version": asset_version})
						job.save(ignore_permissions=True)
						jobs_to_prepare.append(job)
						previous_pipeline_job = job.name
					previous_segment_job = previous_pipeline_job
					if cross_shot_continuity:
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
				):
					dependency = previous_shot_tail_job
				segment_workflow = (
					shot_continuation_workflow
					if shot_continuation_workflow
					and (
						segment["segment_index"] > 1
						or (dependency and dependency == previous_shot_tail_job)
					)
					else shot_workflow
				)
				prompt_text = compile_segment_prompt_from_snapshot(
					frappe._dict(
						name=shot_name,
						shot_number=shot.get("shot_number"),
						generation_prompt=shot.get("generation_prompt"),
						image_prompt=shot.get("image_prompt"),
						motion_plan_json=shot.get("motion_plan_json"),
						start_state=shot.get("start_state"), end_state=shot.get("end_state"),
						handoff_type=shot.get("handoff_type"),
					),
					frappe._dict(snapshot),
					segment["segment_index"],
					len(segments),
					prompt_source=prompt_source_for_workflow(segment_workflow),
					is_final=shot.get("shot_number") == len(snapshot.get("shots") or []),
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
						{"input_role": input_role_for_workflow(shot_workflow), "asset_version": reference.get("asset_version")}
						for reference in references_for_workflow(shot_workflow, shot.get("references"))
						if reference.get("reference_role") and reference.get("asset_version")
					],
				)
				job.save(ignore_permissions=True)
				jobs_to_prepare.append(job)
				previous_segment_job = job.name
			previous_shot_tail_job = previous_segment_job if cross_shot_continuity else None

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
	except Exception as exc:
		_raise_run_error(run, _exception_message(exc))
		return _run_summary(run)

	_refresh_run_counters(run)
	_enqueue_submit_run(run.name)
	return _run_summary(run)


def validate_generation_preflight(project, workflow, shots, *, check_comfyui=False, execution_scope=None):
	if not frappe.conf.get("comfyui_base_url"):
		frappe.throw(_("comfyui_base_url is not configured."))
	if check_comfyui:
		from .comfyui_client import get_system_stats

		get_system_stats()

	from joymedia.services.project_context import build_project_snapshot
	from .workflow_profiles import choose_shot_workflow
	try:
		snapshot = json.loads(build_project_snapshot(project)[0])
	except (TypeError, ValueError):
		frappe.throw(_("The project snapshot could not be prepared for preflight."))
	snapshot_shots = {row.get("shot"): row for row in snapshot.get("shots") or []}

	for shot_row in shots:
		shot = frappe.get_doc("Shot", shot_row.name)
		shot_snapshot = snapshot_shots.get(shot.name, {
			"shot": shot.name,
			"shot_number": shot.shot_number,
			"planned_frame_count": shot.planned_frame_count,
			"generation_prompt": shot.generation_prompt,
			"references": [
				{"reference_role": row.reference_role, "asset_version": row.asset_version}
				for row in shot.generation_inputs or []
			],
		})
		shot_workflow = choose_shot_workflow(snapshot, shot_snapshot)
		shot_pipeline = pipeline_for_final_workflow(shot_workflow.name)
		pipeline_steps = get_pipeline_steps(shot_pipeline.name) if shot_pipeline else []
		validate_workflow_for_execution(shot_workflow)
		validate_workflow_bindings(shot_workflow)
		for pipeline_step in pipeline_steps:
			validate_workflow_for_execution(frappe.get_doc("Generation Workflow", pipeline_step.workflow))
			validate_workflow_bindings(frappe.get_doc("Generation Workflow", pipeline_step.workflow))
		continuation_workflow = _continuation_workflow(shot_workflow)
		if continuation_workflow:
			validate_workflow_for_execution(continuation_workflow)
			validate_workflow_bindings(continuation_workflow)
		required_roles = {
			frappe.scrub(binding.required_input_role)
			for binding in shot_workflow.bindings
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
		mappings = {}
		for reference in references_for_workflow(shot_workflow, shot_snapshot.get("references")):
			if reference.get("asset_version"):
				mappings.setdefault(input_role_for_workflow(shot_workflow), []).append(reference["asset_version"])
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
				)
			):
				continue
			asset_versions = mappings.get(role, [])
			if not asset_versions or any(
				not frappe.db.get_value("Asset Version", asset_version, "file")
				for asset_version in asset_versions
			):
				frappe.throw(
					_("Shot {0} requires usable input(s) with role '{1}'.").format(
						shot.name, role
					)
				)
			validate_role_input_count(shot_workflow, role, len(asset_versions))

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


def submit_run(run_name: str):
	"""Create and submit outstanding attempts for prepared Jobs in this run."""
	# This lock and the database count form the single capacity boundary for all
	# campaigns. Per-run ordering remains strict for last-frame continuity, while
	# capacity is controlled once for the whole ComfyUI endpoint.
	with filelock("joymedia-global-dispatch"):
		return _submit_run_with_global_capacity(run_name)


def _submit_run_with_global_capacity(run_name: str):
	with filelock(f"joymedia-submit-run-{run_name}"):
		run = frappe.get_doc("Generation Run", run_name)
		if run.status == "Cancelled":
			return _run_summary(run)
		if run.status not in ACTIVE_RUN_STATUSES:
			return _run_summary(run)
		if _next_fair_run_name() != run.name:
			return _run_summary(run)

		run.status = "Running"
		if not run.started_at:
			run.started_at = now()
		run.db_set(
			{"status": run.status, "started_at": run.started_at},
			update_modified=False,
		)

		for job_name in _submission_order(run.name):
			job = frappe.get_doc("Generation Task", job_name)
			if job.status in ("Completed", "Failed", "Cancelled", "Running"):
				continue

			if job.status not in ("Ready", "Queued"):
				continue

			if not attach_chained_first_frame(job):
				continue

			if not _has_submission_capacity(run) or not _has_global_submission_capacity():
				break

			if job.status == "Ready":
				job.status = "Queued"
				job.queued_at = now()
				job.save(ignore_permissions=True)

			attempt_names = _create_initial_attempts(job) + _get_pending_attempt_names(job.name)
			for attempt_name in dict.fromkeys(attempt_names):
				_submit_attempt_or_record_failure(attempt_name)

		return refresh_run(run.name)


def refresh_run(run_name: str, enqueue_finalization: bool = True):
	"""Refresh attempt state, aggregate Job counters, and advance the Run lifecycle."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status == "Cancelled":
		return _run_summary(run)
	if run.status in ACTIVE_RUN_STATUSES:
		try:
			for job_name in _get_run_job_names(run.name):
				job = frappe.get_doc("Generation Task", job_name)
				validate_workflow_for_execution(frappe.get_doc("Generation Workflow", job.workflow))
		except Exception as exc:
			message = _exception_message(exc)
			for job_name in _get_run_job_names(run.name):
				if frappe.db.get_value("Generation Task", job_name, "status") in ("Completed", "Failed", "Cancelled"):
					continue
				frappe.db.set_value(
					"Generation Task",
					job_name,
					{
						"status": "Failed",
						"error_summary": "The selected video setup is unavailable. Please try again or contact support.",
						"failure_class": "Workflow",
						"completed_at": now(),
					},
					update_modified=False,
				)
			_raise_run_error(run, message)
			return _run_summary(run)

	for attempt_name in _get_active_attempt_names(run.name):
		try:
			sync_attempt_result(attempt_name)
		except Exception:
			frappe.logger("joymedia.generation_run").exception(
				"Unable to refresh Generation Attempt %s for Run %s", attempt_name, run.name
			)

	return _advance_run(run, enqueue_finalization=enqueue_finalization)


def refresh_generation_state_for_attempt(attempt_name: str):
	"""Derive the parent Job and Run state after an Attempt state change."""
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	job = frappe.get_doc("Generation Task", attempt.generation_task)
	if not job.generation_run:
		_update_job_summary(job)
		return {"generation_task": job.name, "job_status": job.status}

	run = frappe.get_doc("Generation Run", job.generation_run)
	if run.status == "Cancelled":
		return _run_summary(run)
	return _advance_run(run)


def _advance_run(run, enqueue_finalization=True):
	"""Advance jobs, retries, chained submissions, and run completion together."""
	jobs = [frappe.get_doc("Generation Task", job_name) for job_name in _get_run_job_names(run.name)]
	for job in jobs:
		_update_job_summary(job)
	_finalize_completed_shots(run)

	if _create_retry_attempt(run, jobs):
		_enqueue_submit_run(run.name)
	elif _has_submittable_work(run.name) and _has_submission_capacity(run):
		_enqueue_submit_run(run.name)

	previous_status = run.status
	_refresh_run_counters(run)
	sync_media_project_status_for_run(run.name)
	if run.status == "Completed" and previous_status != "Completed":
		_finish_film(run.media_project)
	return _run_summary(run)


def _finish_film(project_name):
	"""Add transitions and the soundtrack as soon as every scene has rendered."""
	from .post_production import queue_post_production_internal

	try:
		queue_post_production_internal(project_name)
	except Exception:
		frappe.logger("joymedia.generation_run").exception("Unable to queue Finish film for %s", project_name)


def enqueue_finalization_if_ready(run_name: str):
	"""Retained for compatibility; generation no longer queues project export."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status != "Cancelled":
		_refresh_run_counters(run)
	return _run_summary(run)


@frappe.whitelist()
def finalize_run_from_ui(run_name: str):
	frappe.throw(_("Generation runs are exported from the editor."))


@frappe.whitelist()
def retry_failed_jobs_from_ui(run_name: str):
	"""Retry and submit the latest failed Attempt chain for every failed Job in a Run."""
	frappe.has_permission("Generation Run", "write", run_name, throw=True)
	return retry_failed_jobs_internal(run_name)


def retry_failed_jobs_internal(run_name: str):
	"""Retry failed Jobs after the owning Campaign has authorized the operation."""
	with filelock(f"joymedia-retry-run-{run_name}"):
		run = frappe.get_doc("Generation Run", run_name)
		if run.status != "Failed":
			frappe.throw(_("Only Failed runs can be retried."))

		job_names = frappe.get_all(
			"Generation Task",
			filters={
				"generation_run": run.name,
				"status": "Failed",
			},
			pluck="name",
		)
		if not job_names:
			frappe.throw(_("This run has no failed Jobs to retry."))

		results = []
		for job_name in job_names:
			job = frappe.get_doc("Generation Task", job_name)
			results.extend(_retry_and_submit_latest_failed_attempts(job, "Execution Failure"))

		if not results:
			frappe.throw(_("No retry Attempts could be created."))

		frappe.db.commit()
		run.reload()
		return {"run": run.name, "status": run.status, "attempts": results}


@frappe.whitelist()
def retry_generation_task_from_ui(job_name: str, reason: str = "Execution Failure"):
	"""Create and immediately submit successor Attempts for a failed Job."""
	frappe.has_permission("Generation Task", "write", job_name, throw=True)
	with filelock(f"joymedia-retry-job-{job_name}"):
		job = frappe.get_doc("Generation Task", job_name)
		if job.status != "Failed":
			frappe.throw(_("Only Failed Generation Tasks can be retried."))

		results = _retry_and_submit_latest_failed_attempts(job, reason)
		if not results:
			frappe.throw(_("This Generation Task has no failed Attempts to retry."))

		frappe.db.commit()
		return {"generation_task": job.name, "attempts": results}


def finalize_run(run_name: str):
	"""Reject the removed generation-level project composition boundary."""
	frappe.throw(_("Generation runs no longer export the project timeline. Use Export from the editor."))


def cancel_run(run_name: str):
	"""Stop orchestration and cancel every task and attempt in a run idempotently."""
	from .comfyui_client import delete_queue_prompts, interrupt
	run = frappe.get_doc("Generation Run", run_name)
	if run.status in ("Completed", "Failed", "Cancelled"):
		return _run_summary(run)

	for attempt_name in frappe.get_all(
		"Generation Attempt", filters={"generation_task": ["in", _get_run_job_names(run.name)]}, pluck="name"
	):
		attempt = frappe.get_doc("Generation Attempt", attempt_name)
		try:
			if attempt.external_job_id and attempt.status == "Queued":
				delete_queue_prompts([attempt.external_job_id], base_url=attempt.comfyui_endpoint_url)
			elif attempt.external_job_id and attempt.status == "Running":
				interrupt(prompt_id=attempt.external_job_id, base_url=attempt.comfyui_endpoint_url)
		except Exception:
			frappe.logger("joymedia.generation_run").exception(
				"Unable to stop ComfyUI prompt %s while cancelling run %s",
				attempt.external_job_id,
				run.name,
			)
	for attempt_name in frappe.get_all(
		"Generation Attempt",
		filters={
			"generation_task": ["in", _get_run_job_names(run.name)],
			"status": ["not in", ["Completed", "Failed", "Cancelled"]],
		},
		pluck="name",
	):
		attempt = frappe.get_doc("Generation Attempt", attempt_name)
		attempt.status = "Cancelled"
		attempt.completed_at = now()
		attempt.failure_class = "Cancelled"
		attempt.error_summary = "Generation was stopped by the user."
		attempt.save(ignore_permissions=True)
	for job_name in _get_run_job_names(run.name):
		job = frappe.get_doc("Generation Task", job_name)
		if job.status not in ("Completed", "Failed", "Cancelled"):
			job.status = "Cancelled"
			job.failure_class = "Cancelled"
			job.error_summary = "Generation was stopped by the user."
			job.save(ignore_permissions=True)

	run.status = "Cancelled"
	run.completed_at = now()
	run.db_set(
		{"status": run.status, "completed_at": run.completed_at},
		update_modified=False,
	)
	return _run_summary(run)


def refresh_active_runs():
	"""Scheduler entry point for all active runs."""
	for run_name in frappe.get_all(
		"Generation Run", filters={"status": ["in", ACTIVE_RUN_STATUSES]}, pluck="name"
	):
		try:
			with filelock(f"joymedia-refresh-run-{run_name}"):
				refresh_run(run_name)
			sync_media_project_status_for_run(run_name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.logger("joymedia.generation_run").exception(
				"Unable to refresh Generation Run %s", run_name
			)
	from .generation_runner import reconcile_attempt_submission
	for attempt_name in frappe.get_all(
		"Generation Attempt", filters={"status": "Submitting"}, pluck="name"
	):
		try:
			reconcile_attempt_submission(attempt_name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.logger("joymedia.generation_run").exception(
				"Unable to reconcile Generation Attempt %s", attempt_name
			)


def sync_media_project_status_for_run(run_name: str):
	"""Derive the customer-facing Campaign status from its generation state."""
	run = frappe.get_doc("Generation Run", run_name)
	media_project = run.media_project
	if not media_project:
		return
	if frappe.db.get_value("Media Project", media_project, "status") == "Archived":
		return
	latest = frappe.get_all(
		"Generation Run", filters={"media_project": media_project}, fields=["name", "status"],
		order_by="creation desc", limit_page_length=1,
	)
	if not latest:
		status = "Draft"
	elif latest[0].status in ACTIVE_RUN_STATUSES or frappe.db.exists(
		# Several scenes may be regenerating in separate runs.
		"Generation Run", {"media_project": media_project, "status": ["in", ACTIVE_RUN_STATUSES]}
	):
		status = "Generating"
	elif latest[0].status == "Completed":
		status = "Completed"
	elif latest[0].status == "Failed":
		status = "Needs Attention"
	elif latest[0].status == "Cancelled":
		status = "Cancelled"
	else:
		status = "Draft"

	frappe.db.set_value("Media Project", media_project, "status", status, update_modified=False)


def _create_initial_attempts(job):
	attempts = _get_job_attempts(job.name)
	if attempts:
		return []
	attempt = frappe.get_doc(
		{
			"doctype": "Generation Attempt",
			"generation_task": job.name,
			"seed": _new_seed(),
			"status": "Pending",
		}
	).insert(ignore_permissions=True)
	# A scene rerender starts a new Generation Run rather than a successor of an
	# old task. Preserve its initiating reason after insertion, when the
	# background worker has actually created the attempt.
	retry_reason = _run_retry_reason(job.generation_run)
	if retry_reason:
		attempt.db_set("retry_reason", retry_reason, update_modified=False)
	return [attempt.name]


def _run_retry_reason(run_name):
	if not run_name:
		return None
	execution_scope_json = frappe.db.get_value("Generation Run", run_name, "execution_scope_json")
	try:
		scope = frappe.parse_json(execution_scope_json or "{}")
	except (TypeError, ValueError):
		return None
	return scope.get("retry_reason") if isinstance(scope, dict) else None


def _create_retry_attempt(run, jobs):

	for job in jobs:
		attempts = _get_job_attempts(job.name)
		effective_attempt = get_effective_attempt_from_history(attempts)
		active_attempts = [attempt for attempt in attempts if attempt.status in ACTIVE_ATTEMPT_STATUSES]
		retry_attempts = [attempt for attempt in attempts if attempt.retry_of]
		if (
			not effective_attempt
			or effective_attempt.status != "Failed"
			or active_attempts
			# Invalid inputs and unavailable/authenticated workflow providers need a
			# human change. Retrying them automatically only creates phantom queue
			# activity and hides the real action from the user.
			or effective_attempt.failure_class in {"Workflow", "Input"}
			or len(retry_attempts) >= MAX_AUTOMATIC_RETRIES
		):
			continue

		job.status = "Queued"
		job.queued_at = now()
		job.save(ignore_permissions=True)
		create_retry_attempt_internal(effective_attempt.name, "Execution Failure")
		return True
	return False


def _retry_and_submit_latest_failed_attempts(job, reason):
	"""Create and submit exactly one successor for each terminal failed attempt chain."""
	attempts = _get_job_attempts(job.name)
	if not job.get("inputs") and callable(
		getattr(job, "get_shot_input_snapshot", None)
	):
		ensure_generation_inputs(job)
	if not attempts and job.status == "Failed":
		# Preparation/configuration failures can leave a failed Job without an
		# Attempt. Create the initial attempt so Retry can submit the repaired
		# workflow instead of incorrectly reporting that nothing is retryable.
		job.db_set("status", "Queued", update_modified=False)
		job.reload()
		attempts = _create_initial_attempts(job)
		results = []
		for attempt_name in attempts:
			submission = _submit_attempt_or_record_failure(attempt_name)
			refresh_generation_state_for_attempt(attempt_name)
			attempt = frappe.get_doc("Generation Attempt", attempt_name)
			results.append(
				{
					"name": attempt.name,
					"status": attempt.status,
					"deferred": bool(submission and submission.get("deferred")),
				}
			)
		return results
	effective_attempt = get_effective_attempt_from_history(attempts)
	failed_attempt_names = [effective_attempt.name] if effective_attempt and effective_attempt.status == "Failed" else []
	results = []
	for attempt_name in failed_attempt_names:
		retry_attempt = create_retry_attempt_internal(attempt_name, reason)
		submission = _submit_attempt_or_record_failure(retry_attempt.name)
		refresh_generation_state_for_attempt(retry_attempt.name)
		attempt = frappe.get_doc("Generation Attempt", retry_attempt.name)
		results.append(
			{
				"name": attempt.name,
				"status": attempt.status,
				"deferred": bool(submission and submission.get("deferred")),
			}
		)
	return results


def _submit_attempt_or_record_failure(attempt_name):
	try:
		return submit_attempt(attempt_name)
	except Exception as exc:
		from .user_messages import classify_failure, friendly_failure, technical_message
		attempt = frappe.get_doc("Generation Attempt", attempt_name)
		if attempt.status == "Pending":
			failure_class = classify_failure(exc, "Generation")
			error_message = _exception_message(exc)
			attempt.status = "Failed"
			attempt.failure_class = failure_class
			attempt.error_summary = friendly_failure(failure_class, error_message)
			attempt.error_details = technical_message(error_message)
			attempt.save(ignore_permissions=True)
		return {"error": attempt.error_summary}


def _update_job_summary(job):
	attempts = _get_job_attempts(job.name)
	effective_attempt = get_effective_attempt_from_history(attempts)
	if not effective_attempt:
		return

	if effective_attempt.status == "Running":
		job.status = "Running"
		job.started_at = job.started_at or now()
	elif effective_attempt.status in {"Pending", "Submitting", "Queued"}:
		job.status = "Queued"
	elif effective_attempt.status == "Completed":
		job.status = "Completed"
		job.progress = 100
		job.completed_at = job.completed_at or now()
		job.failure_class = None
		job.error_summary = None
	elif effective_attempt.status in {"Failed", "Cancelled"}:
		job.status = "Cancelled" if effective_attempt.status == "Cancelled" else "Failed"
		job.progress = 0
		job.completed_at = job.completed_at or now()
		job.failure_class = effective_attempt.get("failure_class") if effective_attempt.status == "Failed" else None
		failure_summary = effective_attempt.get("error_summary")
		if effective_attempt.status == "Failed":
			# Older attempts can predate classification of ComfyUI node failures.
			# Re-evaluate their technical detail while aggregating so a project never
			# presents an authentication problem as a vague, retryable render error.
			from .user_messages import classify_failure, friendly_failure

			detected_failure_class = classify_failure(
				effective_attempt.get("error_details") or failure_summary,
				job.failure_class or "Generation",
			)
			technical_detail = str(effective_attempt.get("error_details") or failure_summary or "").lower()
			is_authentication_failure = any(
				token in technical_detail
				for token in ("unauthorized", "forbidden", "please login", "authentication", "not authenticated")
			)
			if detected_failure_class == "Workflow" and is_authentication_failure:
				job.failure_class = detected_failure_class
				failure_summary = friendly_failure(
					detected_failure_class,
					effective_attempt.get("error_details") or failure_summary,
				)
		job.error_summary = (
			failure_summary
			if effective_attempt.status == "Failed"
			and (effective_attempt.get("error_details") or failure_summary)
			else _("All execution attempts failed.")
		)
	# Job counters are derived from immutable Attempt history. A retry creates an
	# Attempt immediately after moving its Job to Queued, so a normal ORM save can
	# race with that state transition and roll the retry transaction back.
	job.db_set(
		{
			"progress": getattr(job, "progress", 0),
			"status": job.status,
			"started_at": job.started_at,
			"completed_at": job.completed_at,
			"failure_class": job.failure_class,
			"error_summary": job.error_summary,
		},
		notify=True,
	)


def _refresh_run_counters(run):
	jobs = frappe.get_all(
		"Generation Task",
		filters={"generation_run": run.name},
		fields=["status", "failure_class", "error_summary"],
	)
	run.total_tasks = len(jobs)
	run.completed_tasks = sum(job.status == "Completed" for job in jobs)
	run.failed_tasks = sum(job.status == "Failed" for job in jobs)
	run.running_tasks = sum(job.status == "Running" for job in jobs)
	run.progress = round(run.completed_tasks / run.total_tasks * 100, 2) if run.total_tasks else 0

	if run.total_tasks and run.completed_tasks == run.total_tasks:
		if _run_outputs_are_selected(run.name):
			run.status = "Completed"
			run.completed_at = run.completed_at or now()
		else:
			run.status = "Running"
			run.completed_at = None
	elif run.total_tasks and run.failed_tasks > 0:
		active_tasks = any(job.status in ("Pending", "Ready", "Queued", "Running") for job in jobs)
		run.status = "Running" if active_tasks else "Failed"
		run.completed_at = None if active_tasks else (run.completed_at or now())
		latest_failed_job = next(
			(
				job
				for job in reversed(jobs)
				if job.status == "Failed" and job.error_summary
			),
			None,
		)
		run.failure_class = latest_failed_job.failure_class if latest_failed_job else None
		run.error_summary = (
			"Some scenes need attention while other scenes are still rendering."
			if active_tasks
			else latest_failed_job.error_summary if latest_failed_job else None
		)
	elif run.total_tasks and any(job.status == "Running" for job in jobs):
		run.status = "Running"
		run.failure_class = None
		run.error_summary = None
	elif run.total_tasks and any(job.status in ("Ready", "Queued") for job in jobs):
		run.status = "Queued"
		run.failure_class = None
		run.error_summary = None
	# Run counters are derived system state. Result ingestion can update the same
	# Run while this aggregation is in progress, so an ORM save of a stale document
	# would roll back the whole background job after ComfyUI has accepted a prompt.
	run.db_set(
		{
			"total_tasks": run.total_tasks,
			"completed_tasks": run.completed_tasks,
			"failed_tasks": run.failed_tasks,
			"running_tasks": run.running_tasks,
			"progress": run.progress,
			"status": run.status,
			"completed_at": run.completed_at,
			"failure_class": run.failure_class,
			"error_summary": run.error_summary,
		},
		notify=True,
	)


def _run_outputs_are_selected(run_name):
	for job in frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name},
		fields=["shot"],
	):
		if not frappe.db.get_value("Shot", job.shot, "selected_output_asset_version"):
			return False
	return True


def _finalize_completed_shots(run):
	shot_names = frappe.get_all(
		"Generation Task",
		filters={"generation_run": run.name},
		pluck="shot",
	)
	for shot_name in dict.fromkeys(shot_names):
		if _keeps_selected_output(run, shot_name):
			continue
		jobs = frappe.get_all(
			"Generation Task",
			filters={"generation_run": run.name, "shot": shot_name},
			fields=["status"],
		)
		if jobs and all(job.status == "Completed" for job in jobs):
			last_jobs = frappe.get_all(
				"Generation Task",
				filters={"generation_run": run.name, "shot": shot_name},
				fields=["workflow", "segment_index"],
				order_by="segment_index desc, creation desc",
			)
			last_job = next(
				(job for job in last_jobs if frappe.db.get_value("Generation Workflow", job.workflow, "output_media_type") == "Video"),
				None,
			)
			workflow = frappe.get_doc(
				"Generation Workflow", last_job.workflow if last_job else run.workflow
			)
			assembled_version = compose_shot_segments(run.name, shot_name)
			if assembled_version:
				from .timeline_editor import sync_timeline_source_for_shot
				sync_timeline_source_for_shot(shot_name)


def _keeps_selected_output(run, shot_name):
	"""Whether the Shot's current output stays: it has one, and this run does not replace it.

	A "regenerate scene" run replaces the take that was selected when it started, once.
	"""
	selected = frappe.db.get_value("Shot", shot_name, "selected_output_asset_version")
	if not selected:
		return False
	try:
		scope = frappe.parse_json(run.execution_scope_json or "{}") or {}
	except (TypeError, ValueError):
		scope = {}
	if not scope.get("replace_selection"):
		return True
	return frappe.db.get_value("Asset Version", selected, "creation") > run.creation


def _submission_order(run_name):
	"""First segments before continuations, each group in storyboard order.

	First segments and continuations run different models; ComfyUI reloads the model
	whenever consecutive jobs alternate, which adds 1-2.5 minutes per job. Grouping them
	needs one switch per run instead of one per take.
	"""
	rows = frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name},
		fields=["name", "workflow"],
		order_by="creation asc",
	)
	return [row.name for row in sorted(rows, key=lambda row: row.workflow != rows[0].workflow)] if rows else []


def _get_run_job_names(run_name):
	return frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name},
		pluck="name",
		order_by="creation asc",
	)


def _get_job_attempts(job_name):
	return frappe.get_all(
		"Generation Attempt",
		filters={"generation_task": job_name},
		fields=[
			"name",
			"status",
			"retry_of",
			"retry_reason",
			"failure_class",
			"error_summary",
			"error_details",
		],
		order_by="attempt_number asc, creation asc",
	)


def _get_pending_attempt_names(job_name):
	return frappe.get_all(
		"Generation Attempt",
		filters={"generation_task": job_name, "status": "Pending"},
		pluck="name",
		order_by="attempt_number asc, creation asc",
	)


def _get_active_attempt_names(run_name):
	job_names = _get_run_job_names(run_name)
	if not job_names:
		return []
	return frappe.get_all(
		"Generation Attempt",
		filters={"generation_task": ["in", job_names], "status": ["in", ["Queued", "Running"]]},
		pluck="name",
	)


def _get_pending_attempt_names_for_run(run_name):
	job_names = _get_run_job_names(run_name)
	if not job_names:
		return []
	return frappe.get_all(
		"Generation Attempt",
		filters={"generation_task": ["in", job_names], "status": "Pending"},
		pluck="name",
	)


def _has_submittable_work(run_name):
	if _get_pending_attempt_names_for_run(run_name):
		return True
	ready_or_queued = frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name, "status": ["in", ["Ready", "Queued"]]},
		pluck="name",
	)
	# A task is switched to Queued immediately before its first attempt is
	# created. If capacity is consumed in that small interval it must remain
	# dispatchable; otherwise it is stranded until a human retries the run.
	return any(
		frappe.db.count("Generation Attempt", {"generation_task": task_name}) == 0
		for task_name in ready_or_queued
	)


def _has_submission_capacity(run):
	"""Whether this run may put another job into ComfyUI's queue.

	Only one attempt may be queued or running for a run at a time.  The result
	ingestor calls ``refresh_run`` after completion, which then releases the next
	job and lets chained-frame validation attach the completed Last Frame.
	"""
	job_names = _get_run_job_names(run.name)
	if not job_names:
		return True
	in_flight = frappe.db.count(
		"Generation Attempt",
		{"generation_task": ["in", job_names], "status": ["in", ["Submitting", "Queued", "Running"]]},
	)
	return in_flight < MAX_JOBS_IN_FLIGHT_PER_RUN


def _global_submission_limit():
	"""Configured endpoint capacity. Increase only when the worker can sustain it."""
	try:
		return max(1, int(frappe.conf.get("joymedia_max_active_attempts", 1)))
	except (TypeError, ValueError):
		return 1


def _has_global_submission_capacity():
	active = frappe.db.count(
		"Generation Attempt", {"status": ["in", ["Submitting", "Queued", "Running"]]}
	)
	return active < _global_submission_limit()


def _next_fair_run_name():
	"""Choose the ready run that has waited longest since its last dispatch.

	The policy is intentionally independent of workflow/model names. It alternates
	between campaigns when capacity is one, and remains deterministic under the
	global dispatch lock.
	"""
	candidates = []
	for run in frappe.get_all(
		"Generation Run", filters={"status": ["in", ACTIVE_RUN_STATUSES]},
		fields=["name", "creation"], order_by="creation asc",
	):
		if not _has_submittable_work(run.name):
			continue
		last_dispatch = frappe.db.get_value(
			"Generation Attempt",
			{"generation_task": ["in", _get_run_job_names(run.name)]},
			"queued_at", order_by="queued_at desc",
		)
		# A run that has never received capacity is always served first; creation
		# is the deterministic tie-breaker. Keep timestamps as timestamps: Frappe
		# returns ``datetime`` values here, so a string sentinel makes Python's
		# tuple comparison fail as soon as both kinds are present.
		candidates.append((0 if last_dispatch is None else 1, last_dispatch or run.creation, run.creation, run.name))
	return min(candidates)[3] if candidates else None


def _enqueue(method_name, run_name):
	frappe.enqueue(
		f"joymedia.services.generation_orchestrator.{method_name}",
		queue="long",
		run_name=run_name,
		enqueue_after_commit=True,
		job_id=f"joymedia:{method_name}:{run_name}",
		deduplicate=True,
	)


def _enqueue_submit_run(run_name):
	"""Queue the next submission stage with a job-specific deduplication key."""
	next_job = frappe.db.get_value(
		"Generation Task",
		{"generation_run": run_name, "status": "Ready"},
		"name",
		order_by="creation asc",
	)
	if not next_job:
		next_job = frappe.db.get_value(
			"Generation Task",
			{"generation_run": run_name, "status": "Queued"},
			"name",
			order_by="creation asc",
		)
	if not next_job:
		return
	frappe.enqueue(
		"joymedia.services.generation_orchestrator.submit_run",
		queue="long",
		run_name=run_name,
		enqueue_after_commit=True,
		job_id=f"joymedia:submit_run:{run_name}:{next_job}",
		deduplicate=True,
	)


def _raise_run_error(run, message):
	run.status = "Failed"
	run.error_summary = message or _("Generation run failed.")
	run.completed_at = now()
	run.db_set(
		{
			"status": run.status,
			"error_summary": run.error_summary,
			"completed_at": run.completed_at,
		},
		update_modified=False,
	)
	sync_media_project_status_for_run(run.name)


def _exception_message(exc):
	return str(exc).strip() or exc.__class__.__name__


def _run_summary(run):
	return {
		"name": run.name,
		"status": run.status,
		"total_tasks": run.total_tasks,
		"completed_tasks": run.completed_tasks,
		"failed_tasks": run.failed_tasks,
		"running_tasks": run.running_tasks,
		"progress": run.progress,
	}


def _new_seed():
	return secrets.randbelow(2_147_483_648)
