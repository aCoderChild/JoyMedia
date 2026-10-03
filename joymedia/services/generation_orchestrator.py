import hashlib
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
from .prompt_compiler import compile_segment_prompt_from_snapshot
from .result_ingestor import sync_attempt_result
from .video_composer import compose_shot_segments
from .workflow_resolver import (
	validate_workflow_bindings,
	validate_workflow_for_execution,
)


ACTIVE_RUN_STATUSES = ("Queued", "Running")
ACTIVE_ATTEMPT_STATUSES = ("Pending", "Queued", "Running")
TERMINAL_ATTEMPT_STATUSES = ("Completed", "Failed", "Cancelled")
TERMINAL_JOB_STATUSES = ("Completed", "Failed", "Cancelled")
MAX_AUTOMATIC_RETRIES = 1


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
		jobs_to_prepare = []
		previous_shot_tail_job = execution_scope.get("continuation_from_task") if execution_scope.get("continuity") else None
		for shot in shots:
			shot_name = shot.get("shot")
			segments = plan_generation_segments(
				shot.get("planned_frame_count"),
				max_segment_frames=workflow.frame_count,
			)
			previous_segment_job = None
			for segment in segments:
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
				if not dependency and (
					snapshot.get("generation_mode") in ("Continuous", "Consistency")
					or execution_scope.get("continuity")
				):
					dependency = previous_shot_tail_job
				prompt_text = compile_segment_prompt_from_snapshot(
					frappe._dict(
						name=shot_name,
						shot_number=shot.get("shot_number"),
						generation_prompt=shot.get("generation_prompt"),
					),
					frappe._dict(snapshot),
					segment["segment_index"],
					len(segments),
				)
				job = frappe.get_doc(
					{
						"doctype": "Generation Task",
						"generation_run": run.name,
					"shot": shot_name,
						"workflow": run.workflow,
						"prompt_text": prompt_text,
						"prompt_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
						"status": "Draft",
						"segment_index": segment["segment_index"],
						"segment_frame_count": segment["segment_frame_count"],
						"depends_on_task": dependency,
					}
				).insert(ignore_permissions=True)
				job.set(
					"inputs",
					[
						{"input_role": reference.get("reference_role"), "asset_version": reference.get("asset_version")}
						for reference in shot.get("references") or []
						if reference.get("reference_role") and reference.get("asset_version")
					],
				)
				job.save(ignore_permissions=True)
				jobs_to_prepare.append(job)
				previous_segment_job = job.name
			previous_shot_tail_job = previous_segment_job

		for job in jobs_to_prepare:
			shot_snapshot = next(
				(item for item in shots if item.get("shot") == job.shot),
				{"references": []},
			)
			prepare_generation_task(job.name, shot_snapshot.get("references"))
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

	validate_workflow_for_execution(workflow)
	validate_workflow_bindings(workflow)
	required_roles = {
		frappe.scrub(binding.required_input_role)
		for binding in workflow.bindings
		if binding.required
		and binding.required_input_role
	}

	for shot_row in shots:
		shot = frappe.get_doc("Shot", shot_row.name)
		if not (shot.generation_prompt or "").strip():
			frappe.throw(
				_("Shot {0} has no generation prompt. Regenerate or edit the storyboard first.").format(
					shot.name
				)
			)

		mappings = {}
		for mapping in shot.generation_inputs:
			if mapping.reference_role and mapping.asset_version:
				mappings.setdefault(frappe.scrub(mapping.reference_role), []).append(mapping.asset_version)
		for role in required_roles:
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
			binding = next(
				(binding for binding in workflow.bindings
				 if binding.required and frappe.scrub(binding.required_input_role or "") == role),
				None,
			)
			if binding and binding.value_type != "File Paths" and len(asset_versions) != 1:
				frappe.throw(
					_("Workflow binding for role '{0}' accepts exactly one input; found {1}.").format(
						role, len(asset_versions)
					)
				)

		segments = plan_generation_segments(
			shot_row.planned_frame_count,
			max_segment_frames=workflow.frame_count,
		)
		if not segments:
			frappe.throw(_("Shot {0} has no generation segments.").format(shot.name))
		if any(segment["segment_frame_count"] > workflow.frame_count for segment in segments):
			frappe.throw(
				_("Shot {0} contains a segment larger than Workflow frame capacity.").format(shot.name)
			)


def submit_run(run_name: str):
	"""Create and submit outstanding attempts for prepared Jobs in this run."""
	with filelock(f"joymedia-submit-run-{run_name}"):
		run = frappe.get_doc("Generation Run", run_name)
		if run.status == "Cancelled":
			return _run_summary(run)
		if run.status not in ACTIVE_RUN_STATUSES:
			return _run_summary(run)

		run.status = "Running"
		if not run.started_at:
			run.started_at = now()
		run.db_set(
		{"status": run.status, "started_at": run.started_at},
		update_modified=False,
	)

		for job_name in _get_run_job_names(run.name):
			job = frappe.get_doc("Generation Task", job_name)
			if job.status in ("Completed", "Failed", "Cancelled", "Running"):
				continue

			if job.status not in ("Ready", "Queued"):
				continue

			if not attach_chained_first_frame(job):
				continue

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
			workflow = frappe.get_doc("Generation Workflow", run.workflow)
			validate_workflow_for_execution(workflow)
		except Exception as exc:
			message = _exception_message(exc)
			for job_name in _get_run_job_names(run.name):
				frappe.db.set_value(
					"Generation Task",
					job_name,
					{
						"status": "Failed",
						"error_summary": message,
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

	_refresh_run_counters(run)
	sync_media_project_status_for_run(run.name)
	return _run_summary(run)


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


def prepare_chained_regeneration(attempt_name: str):
	"""Invalidate downstream chained outputs before replacing one completed shot."""
	generation_task_name = frappe.db.get_value(
		"Generation Attempt", attempt_name, "generation_task"
	)
	shot_name = frappe.db.get_value(
		"Generation Task", generation_task_name, "shot"
	)
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	job = frappe.get_doc("Generation Task", attempt.generation_task)
	shot = frappe.get_doc("Shot", job.shot)
	project = frappe.get_doc("Media Project", shot.media_project)
	run_snapshot = {}
	if job.generation_run:
		run = frappe.get_doc("Generation Run", job.generation_run)
		try:
			run_snapshot = frappe.parse_json(run.project_snapshot_json or "{}")
		except (TypeError, ValueError):
			frappe.throw(_("Generation Run {0} has invalid project snapshot JSON.").format(run.name))
	if not job.generation_run:
		return []

	jobs = frappe.get_all(
		"Generation Task",
		filters={"generation_run": job.generation_run},
		fields=["name", "depends_on_task", "status", "shot"],
		order_by="creation asc",
	)
	children_by_parent = {}
	for row in jobs:
		if row.depends_on_task:
			children_by_parent.setdefault(row.depends_on_task, []).append(row)

	downstream = []
	frontier = [job.name]
	while frontier:
		parent = frontier.pop(0)
		for child in children_by_parent.get(parent, []):
			if (
				child.shot != shot.shot
				and run_snapshot.get("generation_mode") not in ("Continuous", "Consistency")
			):
				continue
			downstream.append(child)
			frontier.append(child.name)

	if not downstream:
		return []

	from joymedia.joymedia.doctype.generation_attempt.generation_attempt import (
		create_manual_regeneration_attempt_internal,
		get_effective_attempt,
	)

	regeneration_plan = []
	for downstream_job in downstream:
		active_attempts = frappe.get_all(
			"Generation Attempt",
			filters={
				"generation_task": downstream_job.name,
				"status": ["in", ["Pending", "Queued", "Running"]],
			},
			pluck="name",
		)
		if active_attempts:
			frappe.throw(
				_(
					"Shot {0} is already running. Stop the current sequence before regenerating an earlier shot."
				).format(downstream_job.shot)
			)

		completed_attempt = get_effective_attempt(downstream_job.name)
		if not completed_attempt or completed_attempt.status != "Completed":
			frappe.throw(
				_("Shot {0} has no completed output to invalidate.").format(
					downstream_job.shot
				)
			)

		if frappe.db.exists("Generation Attempt", {"retry_of": completed_attempt.name}):
			frappe.throw(
				_(
					"Shot {0} already has a regeneration successor. Resolve that regeneration before starting another sequence."
				).format(downstream_job.shot)
			)

		regeneration_plan.append((downstream_job.shot, completed_attempt.name))

	prepared = []
	for shot, completed_attempt in regeneration_plan:
		frappe.db.set_value(
			"Shot",
			shot,
			"selected_output_asset_version",
			None,
			update_modified=False,
		)
		retry_attempt = create_manual_regeneration_attempt_internal(completed_attempt, "Reroll")
		prepared.append(retry_attempt.name)

	return prepared


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
		if attempt.external_job_id and attempt.status == "Queued":
			delete_queue_prompts([attempt.external_job_id], base_url=attempt.comfyui_endpoint_url)
		elif attempt.external_job_id and attempt.status == "Running":
			interrupt(base_url=attempt.comfyui_endpoint_url)
	for attempt_name in _get_pending_attempt_names_for_run(run.name):
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
			refresh_run(run_name)
			sync_media_project_status_for_run(run_name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.logger("joymedia.generation_run").exception(
				"Unable to refresh Generation Run %s", run_name
			)


def sync_media_project_status_for_run(run_name: str):
	"""Derive the customer-facing Campaign status from its generation state."""
	run = frappe.get_doc("Generation Run", run_name)
	media_project = run.media_project
	if not media_project:
		return
	latest = frappe.get_all(
		"Generation Run", filters={"media_project": media_project}, fields=["name", "status"],
		order_by="creation desc", limit_page_length=1,
	)
	if not latest:
		status = "Draft"
	elif latest[0].status in ACTIVE_RUN_STATUSES:
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
	return [attempt.name]


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
		attempt = frappe.get_doc("Generation Attempt", attempt_name)
		if attempt.status == "Pending":
			error_message = _exception_message(exc)
			attempt.status = "Failed"
			attempt.error_summary = error_message
			attempt.error_details = error_message
			attempt.save(ignore_permissions=True)
		return {"error": _exception_message(exc)}


def _update_job_summary(job):
	attempts = _get_job_attempts(job.name)
	effective_attempt = get_effective_attempt_from_history(attempts)
	if not effective_attempt:
		return

	if effective_attempt.status == "Running":
		job.status = "Running"
		job.started_at = job.started_at or now()
	elif effective_attempt.status in {"Pending", "Queued"}:
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
		job.error_summary = (
			(effective_attempt.get("error_details") or effective_attempt.get("error_summary"))
			if effective_attempt.status == "Failed"
			and (effective_attempt.get("error_details") or effective_attempt.get("error_summary"))
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
		run.status = "Failed"
		run.completed_at = run.completed_at or now()
		latest_failed_job = next(
			(
				job
				for job in reversed(jobs)
				if job.status == "Failed" and job.error_summary
			),
			None,
		)
		run.failure_class = latest_failed_job.failure_class if latest_failed_job else None
		run.error_summary = latest_failed_job.error_summary if latest_failed_job else None
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
		if frappe.db.get_value("Shot", shot_name, "selected_output_asset_version"):
			continue
		jobs = frappe.get_all(
			"Generation Task",
			filters={"generation_run": run.name, "shot": shot_name},
			fields=["status"],
		)
		if jobs and all(job.status == "Completed" for job in jobs):
			assembled_version = compose_shot_segments(run.name, shot_name)
			if assembled_version:
				from .timeline_editor import sync_timeline_source_for_shot
				sync_timeline_source_for_shot(shot_name)


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
	return bool(
		frappe.db.exists(
			"Generation Task",
			{"generation_run": run_name, "status": "Ready"},
		)
	)


def _has_submission_capacity(run):
	return True


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
