"""Creates and drives Generation Runs. A run is prepared from a project snapshot (one task per scene segment and
pipeline stage), submitted within the GPU's capacity, refreshed as attempts finish, retried, cancelled and
finalised into scene takes. Long scenes are chained segments; a scene with an approved keyframe skips its image stage.
"""

import hashlib
import secrets

import frappe
from frappe import _
from frappe.utils import now
from frappe.utils.synchronization import filelock

from joymedia.joymedia.doctype.generation_attempt.generation_attempt import (
	create_retry_attempt_internal,
	get_effective_attempt_from_history,
)
from joymedia.services.editing.composer import compose_shot_segments
from joymedia.services.generation.ingestor import sync_attempt_result
from joymedia.services.generation.preparation import (
	_continuation_settings,
	_continuation_workflow,
	_pipeline_reference_inputs,
	_pipeline_steps_for_segment,
	_segment_plan,
	prepare_run,
	validate_generation_preflight,
)
from joymedia.services.generation.run_state import (
	ACTIVE_RUN_STATUSES,
	_enqueue,
	_enqueue_submit_run,
	_exception_message,
	_get_run_job_names,
	_is_keyframe_run,
	_raise_run_error,
	_refresh_run_counters,
	_run_outputs_are_selected,
	_run_summary,
	sync_media_project_status_for_run,
)
from joymedia.services.generation.runner import (
	attach_chained_first_frame,
	ensure_generation_inputs,
	submit_attempt,
)
from joymedia.services.workflows.resolver import (
	validate_workflow_for_execution,
)

ACTIVE_ATTEMPT_STATUSES = ("Pending", "Submitting", "Queued", "Running")
TERMINAL_ATTEMPT_STATUSES = ("Completed", "Failed", "Cancelled")
TERMINAL_JOB_STATUSES = ("Completed", "Failed", "Cancelled")
MAX_AUTOMATIC_RETRIES = 1
# Dependency edges, rather than an unconditional serial queue, preserve
# continuity.  Projects in Continuous/Consistency mode retain a capacity of
# one; independent Multi-shot work can use the configured bounded capacity.
# Keep the existing single-GPU behavior until an operator explicitly raises
# ``joymedia_max_independent_jobs_per_run`` together with endpoint capacity.
DEFAULT_MAX_INDEPENDENT_JOBS_IN_FLIGHT = 1


@frappe.whitelist()
def start_run(run_name: str):
	"""Start a Draft Generation Run and hand the remaining workflow to background jobs."""
	frappe.has_permission("Generation Run", "write", run_name, throw=True)
	return start_run_internal(run_name)


def start_run_internal(run_name: str, *, preflight_checked=False):
	"""Start a run after the caller has authorized its owning Campaign."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status != "Draft":
		frappe.throw(_("Generation Run {0} must be Draft to start.").format(run.name))

	project = frappe.get_doc("Media Project", run.media_project)
	_require_project_generation_authorization(project)
	if not preflight_checked:
		validate_run_preflight(run, project)

	run.status = "Queued"
	run.error_summary = None
	run.db_set(
		{"status": run.status, "error_summary": run.error_summary},
		update_modified=False,
	)
	frappe.db.set_value("Media Project", project.name, "status", "Generating", update_modified=False)
	_enqueue("prepare_run", run.name)
	return {"name": run.name, "status": run.status}


def validate_run_preflight(run, project):
	"""Validate before allocating a Run name; remote I/O must not hold global series locks."""
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
				if frappe.db.get_value("Generation Task", job_name, "status") in (
					"Completed",
					"Failed",
					"Cancelled",
				):
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

	# Recover submissions interrupted after the attempt was durably marked
	# ``Submitting`` but before ComfyUI returned a prompt ID. Without this pass,
	# the task owns an attempt forever, so ``_has_submittable_work`` refuses to
	# dispatch the next shot even though the GPU is idle.
	job_names = _get_run_job_names(run.name)
	if job_names:
		from joymedia.services.generation.runner import reconcile_attempt_submission

		for attempt_name in frappe.get_all(
			"Generation Attempt",
			filters={"generation_task": ["in", job_names], "status": "Submitting"},
			pluck="name",
		):
			try:
				reconcile_attempt_submission(attempt_name)
			except Exception:
				frappe.logger("joymedia.generation_run").exception(
					"Unable to reconcile submitting Generation Attempt %s for Run %s",
					attempt_name,
					run.name,
				)

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
	# Attempt synchronization may have waited on network I/O while Stop committed.
	# Result work is complete here; begin aggregation from the current run state.
	frappe.db.commit()
	run.reload()
	if run.status == "Cancelled" or (run.status == "Failed" and run.failure_class == "Finalization"):
		return _run_summary(run)
	jobs = [frappe.get_doc("Generation Task", job_name) for job_name in _get_run_job_names(run.name)]
	for job in jobs:
		_update_job_summary(job)
	# Release status-row locks before normalization and remote composition review.
	frappe.db.commit()
	try:
		_finalize_completed_shots(run)
	except (frappe.ValidationError, frappe.PermissionError, ValueError) as exc:
		frappe.clear_last_message()
		_refresh_run_counters(run)
		# Successful provider inference can still fail delivery or preservation.
		# Keep its real attempts/artifacts, but stop repeatedly composing the same
		# rejected output on every UI poll and scheduler tick.
		frappe.db.set_value(
			"Generation Run",
			{"name": run.name, "status": ["!=", "Cancelled"]},
			{
				"status": "Failed",
				"failure_class": "Finalization",
				"completed_at": now(),
				"error_summary": str(exc)[:2000],
			},
			update_modified=False,
		)
		frappe.db.commit()
		run.reload()
		sync_media_project_status_for_run(run.name)
		return _run_summary(run)

	if _create_retry_attempt(run, jobs):
		_enqueue_submit_run(run.name)
	elif _has_submittable_work(run.name) and _has_submission_capacity(run):
		_enqueue_submit_run(run.name)

	previous_status = run.status
	_refresh_run_counters(run)
	frappe.db.commit()
	run.reload()
	sync_media_project_status_for_run(run.name)
	from joymedia.services.consistency.retention import allows_automatic_finishing

	if (
		run.status == "Completed"
		and previous_status != "Completed"
		and not _is_keyframe_run(run)
		and not (frappe.parse_json(run.execution_scope_json or "{}") or {}).get("candidate_only")
		and allows_automatic_finishing(run)
	):
		_finish_film(run.media_project)
	if run.status in ("Completed", "Failed", "Cancelled") and previous_status != run.status:
		# Scenes the consistency check sent back wait for the project's runs to end, then go in one run.
		frappe.enqueue(
			"joymedia.services.review.consistency.redo_waiting",
			queue="long",
			enqueue_after_commit=True,
			job_id=f"joymedia-redo-{run.media_project}",
			deduplicate=True,
			project_name=run.media_project,
		)
	return _run_summary(run)


def _finish_film(project_name):
	"""Request finishing once every scene has its take."""
	from joymedia.services.editing.post_production import resume_post_production

	return resume_post_production(project_name)


@frappe.whitelist()
def retry_failed_jobs_from_ui(run_name: str):
	"""Retry and submit the latest failed Attempt chain for every failed Job in a Run."""
	frappe.has_permission("Generation Run", "write", run_name, throw=True)
	_require_project_generation_authorization(
		frappe.get_doc("Media Project", frappe.db.get_value("Generation Run", run_name, "media_project"))
	)
	return retry_failed_jobs_internal(run_name)


def _require_run_plan_unchanged(run):
	"""Retry repeats the frozen attempt; a changed plan must be regenerated instead."""
	from joymedia.services.planning.signature import compute_plan_signature

	scope = frappe.parse_json(run.execution_scope_json or "{}")
	signature = scope.get("plan_signature") if isinstance(scope, dict) else None
	if signature and signature != compute_plan_signature(run.media_project):
		frappe.throw(
			_(
				"The storyboard changed after this run started. Retry would repeat the old plan; "
				"regenerate to render the current approved plan."
			)
		)


def retry_failed_jobs_internal(run_name: str):
	"""Retry failed Jobs after the owning Campaign has authorized the operation."""
	with filelock(f"joymedia-retry-run-{run_name}"):
		run = frappe.get_doc("Generation Run", run_name)
		if run.status != "Failed":
			frappe.throw(_("Only Failed runs can be retried."))
		_require_run_plan_unchanged(run)

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
		run = frappe.get_doc("Generation Run", job.generation_run)
		_require_project_generation_authorization(frappe.get_doc("Media Project", run.media_project))
		if job.status != "Failed":
			frappe.throw(_("Only Failed Generation Tasks can be retried."))
		_require_run_plan_unchanged(run)

		results = _retry_and_submit_latest_failed_attempts(job, reason)
		if not results:
			frappe.throw(_("This Generation Task has no failed Attempts to retry."))

		frappe.db.commit()
		return {"generation_task": job.name, "attempts": results}


def _require_project_generation_authorization(project):
	"""Apply project access and storyboard approval at every GPU-work boundary."""
	project._require_write_access()
	if project.storyboard_approval_status != "Approved":
		frappe.throw(_("Review and approve the storyboard before starting or retrying generation."))


def cancel_run(run_name: str):
	"""Persist stop intent before network calls, then cancel nonterminal work.

	Completed artifacts are retained. A repeated cancellation also cleans up a
	previously interrupted stop rather than leaving its queued attempts alive.
	"""
	from joymedia.services.workflows.comfyui import delete_queue_prompts, interrupt

	run = frappe.get_doc("Generation Run", run_name)
	if run.status in ("Completed", "Failed"):
		return _run_summary(run)
	run.status = "Cancelled"
	run.completed_at = run.completed_at or now()
	# No network call may hold the transaction's earlier read snapshot while
	# ingestion changes attempts on another worker (MariaDB error 1020).
	frappe.db.commit()
	frappe.db.set_value(
		"Generation Run",
		run.name,
		{"status": "Cancelled", "completed_at": run.completed_at},
		update_modified=False,
	)
	frappe.db.commit()
	jobs = _get_run_job_names(run.name)
	if jobs:
		attempts = frappe.get_all(
			"Generation Attempt",
			filters={"generation_task": ["in", jobs], "status": ["in", ["Submitting", "Queued", "Running"]]},
			fields=["external_job_id", "status", "comfyui_endpoint_url"],
		)
		frappe.db.commit()
		for attempt in attempts:
			try:
				if attempt.external_job_id and attempt.status == "Queued":
					delete_queue_prompts([attempt.external_job_id], base_url=attempt.comfyui_endpoint_url)
				elif attempt.external_job_id and attempt.status == "Running":
					interrupt(prompt_id=attempt.external_job_id, base_url=attempt.comfyui_endpoint_url)
			except Exception:
				frappe.logger("joymedia.generation_run").exception(
					"Unable to stop ComfyUI prompt %s for %s", attempt.external_job_id, run.name
				)
		frappe.db.commit()
		values = {
			"status": "Cancelled",
			"completed_at": now(),
			"failure_class": "Cancelled",
			"error_summary": "Generation was stopped by the user.",
		}
		# Conditional writes cannot overwrite a completion that won the race.
		frappe.db.set_value(
			"Generation Attempt",
			{"generation_task": ["in", jobs], "status": ["not in", TERMINAL_ATTEMPT_STATUSES]},
			values,
			update_modified=False,
		)
		frappe.db.set_value(
			"Generation Task",
			{"name": ["in", jobs], "status": ["not in", TERMINAL_JOB_STATUSES]},
			values,
			update_modified=False,
		)
	# Report the post-cancellation state, not the counters read before Stop.
	_refresh_run_counters(run)
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
	from joymedia.services.generation.runner import reconcile_attempt_submission

	for attempt_name in frappe.get_all("Generation Attempt", filters={"status": "Submitting"}, pluck="name"):
		try:
			reconcile_attempt_submission(attempt_name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.logger("joymedia.generation_run").exception(
				"Unable to reconcile Generation Attempt %s", attempt_name
			)


def _create_initial_attempts(job):
	attempts = _get_job_attempts(job.name)
	if attempts:
		return []
	attempt = frappe.get_doc(
		{
			"doctype": "Generation Attempt",
			"generation_task": job.name,
			"seed": _initial_seed(job),
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
		from joymedia.services.review.admission import quality_retry

		create_retry_attempt_internal(
			effective_attempt.name,
			"QA Rejection" if quality_retry(effective_attempt) else "Execution Failure",
		)
		return True
	return False


def _revive_cancelled_dependents(job_name):
	"""Return the tasks cancelled only because `job_name` failed to Ready, recursively.

	A failure cancels everything that depends on it. Retrying the failed task must undo that, or the
	retry succeeds and the run still cannot finish. Tasks cancelled for any other reason are left alone.
	"""
	from joymedia.services.generation.ingestor import CASCADE_CANCEL_SUMMARY

	revived = []
	for dependent in frappe.get_all(
		"Generation Task",
		filters={"depends_on_task": job_name, "status": "Cancelled", "error_summary": CASCADE_CANCEL_SUMMARY},
		pluck="name",
	):
		frappe.db.set_value(
			"Generation Task",
			dependent,
			{"status": "Ready", "failure_class": None, "error_summary": None},
			update_modified=False,
		)
		revived.append(dependent)
		revived.extend(_revive_cancelled_dependents(dependent))
	return revived


def _retry_and_submit_latest_failed_attempts(job, reason):
	"""Create and submit exactly one successor for each terminal failed attempt chain."""
	_revive_cancelled_dependents(job.name)
	attempts = _get_job_attempts(job.name)
	if not job.get("inputs") and callable(getattr(job, "get_shot_input_snapshot", None)):
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
	failed_attempt_names = (
		[effective_attempt.name] if effective_attempt and effective_attempt.status == "Failed" else []
	)
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
		from joymedia.services.generation.failures import (
			classify_failure,
			friendly_failure,
			technical_message,
		)

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
	fields = ("progress", "status", "started_at", "completed_at", "failure_class", "error_summary")
	before = {key: job.get(key) for key in fields}
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
		job.failure_class = (
			effective_attempt.get("failure_class") if effective_attempt.status == "Failed" else None
		)
		failure_summary = effective_attempt.get("error_summary")
		if effective_attempt.status == "Failed":
			# Older attempts can predate classification of ComfyUI node failures.
			# Re-evaluate their technical detail while aggregating so a project never
			# presents an authentication problem as a vague, retryable render error.
			from joymedia.services.generation.failures import classify_failure, friendly_failure

			detected_failure_class = classify_failure(
				effective_attempt.get("error_details") or failure_summary,
				job.failure_class or "Generation",
			)
			technical_detail = str(effective_attempt.get("error_details") or failure_summary or "").lower()
			is_authentication_failure = any(
				token in technical_detail
				for token in (
					"unauthorized",
					"forbidden",
					"please login",
					"authentication",
					"not authenticated",
				)
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
	if before == {key: job.get(key) for key in fields}:
		return
	# Job counters are derived from immutable Attempt history. Avoid Document.db_set
	# here: it reloads the row with ``FOR UPDATE`` and can collide with the result
	# ingestor while the browser polls progress. A direct idempotent update has no
	# stale document/version state to reconcile.
	frappe.db.set_value(
		"Generation Task",
		{"name": job.name, "status": ["!=", "Cancelled"]},
		{
			"progress": getattr(job, "progress", 0),
			"status": job.status,
			"started_at": job.started_at,
			"completed_at": job.completed_at,
			"failure_class": job.failure_class,
			"error_summary": job.error_summary,
		},
		update_modified=False,
	)


def _finalize_completed_shots(run):
	shot_names = frappe.get_all(
		"Generation Task",
		filters={"generation_run": run.name},
		pluck="shot",
	)
	if _is_keyframe_run(run):
		from joymedia.services.keyframes.stage import record_keyframe

		for shot_name in dict.fromkeys(shot_names):
			record_keyframe(run.name, shot_name)
		return
	candidate_only = bool((frappe.parse_json(run.execution_scope_json or "{}") or {}).get("candidate_only"))

	from joymedia.services.consistency.retention import needs_candidate_review

	snapshot = frappe.parse_json(run.project_snapshot_json or "{}") or {}
	scenes = {row.get("shot"): row for row in snapshot.get("shots", [])}
	for shot_name in dict.fromkeys(shot_names):
		review_candidate = candidate_only or needs_candidate_review(scenes.get(shot_name, {}))
		if not review_candidate and _keeps_selected_output(run, shot_name):
			continue
		jobs = frappe.get_all(
			"Generation Task",
			filters={"generation_run": run.name, "shot": shot_name},
			fields=["status"],
		)
		if jobs and all(job.status == "Completed" for job in jobs):
			assembled_version = (
				compose_shot_segments(run.name, shot_name, select_output=False)
				if review_candidate
				else compose_shot_segments(run.name, shot_name)
			)
			if (
				assembled_version
				and not review_candidate
				and frappe.db.get_value("Shot", shot_name, "selected_output_asset_version")
				== assembled_version
			):
				from joymedia.services.editing.timeline import update_timeline_source_for_shot

				# Whole-video regeneration replaces the storyboard take. Keep the
				# existing editorial ranges and positions, but bind each video clip
				# to the newly selected Shot output immediately.
				if _run_replaces_selection(run):
					update_timeline_source_for_shot(run.media_project, shot_name)
				else:
					from joymedia.services.editing.timeline import sync_timeline_source_for_shot

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


def _run_replaces_selection(run):
	try:
		scope = frappe.parse_json(run.execution_scope_json or "{}") or {}
	except (TypeError, ValueError):
		return False
	return bool(scope.get("replace_selection"))


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
	return (
		[row.name for row in sorted(rows, key=lambda row: row.workflow != rows[0].workflow)] if rows else []
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

	Tasks with an explicit dependency remain blocked by their dependency state.
	Independent multi-shot tasks may use a small configured pool; continuous
	projects remain serial so the next shot can consume its predecessor's Last
	Frame artifact.
	"""
	job_names = _get_run_job_names(run.name)
	if not job_names:
		return True
	in_flight = frappe.db.count(
		"Generation Attempt",
		{"generation_task": ["in", job_names], "status": ["in", ["Submitting", "Queued", "Running"]]},
	)
	return in_flight < _run_submission_limit(run)


def _run_submission_limit(run):
	generation_mode = (
		frappe.db.get_value("Media Project", run.media_project, "generation_mode") or "Multi-shot"
	)
	if generation_mode in ("Continuous", "Consistency"):
		return 1
	try:
		return max(
			1,
			int(
				frappe.conf.get(
					"joymedia_max_independent_jobs_per_run", DEFAULT_MAX_INDEPENDENT_JOBS_IN_FLIGHT
				)
			),
		)
	except (TypeError, ValueError):
		return DEFAULT_MAX_INDEPENDENT_JOBS_IN_FLIGHT


def _global_submission_limit():
	"""Configured endpoint capacity. Increase only when the worker can sustain it."""
	try:
		return max(1, int(frappe.conf.get("joymedia_max_active_attempts", 1)))
	except (TypeError, ValueError):
		return 1


def _has_global_submission_capacity():
	active = frappe.db.count("Generation Attempt", {"status": ["in", ["Submitting", "Queued", "Running"]]})
	return active < _global_submission_limit()


def _next_fair_run_name():
	"""Choose the ready run that has waited longest since its last dispatch.

	The policy is intentionally independent of workflow/model names. It alternates
	between campaigns when capacity is one, and remains deterministic under the
	global dispatch lock.
	"""
	candidates = []
	for run in frappe.get_all(
		"Generation Run",
		filters={"status": ["in", ACTIVE_RUN_STATUSES]},
		fields=["name", "creation"],
		order_by="creation asc",
	):
		if not _has_submittable_work(run.name):
			continue
		last_dispatch = frappe.db.get_value(
			"Generation Attempt",
			{"generation_task": ["in", _get_run_job_names(run.name)]},
			"queued_at",
			order_by="queued_at desc",
		)
		# A run that has never received capacity is always served first; creation
		# is the deterministic tie-breaker. Keep timestamps as timestamps: Frappe
		# returns ``datetime`` values here, so a string sentinel makes Python's
		# tuple comparison fail as soon as both kinds are present.
		candidates.append(
			(0 if last_dispatch is None else 1, last_dispatch or run.creation, run.creation, run.name)
		)
	return min(candidates)[3] if candidates else None


def _initial_seed(job):
	"""The first frames a run draws share one seed, so the scenes start from the same noise and come out in one style; a
	video, and a frame redrawn on its own (its own run), get a fresh one."""
	if frappe.db.get_value("Generation Workflow", job.workflow, "output_media_type") == "Image":
		scope = frappe.parse_json(
			frappe.db.get_value("Generation Run", job.generation_run, "execution_scope_json") or "{}"
		)
		seed = scope.get("keyframe_seed") if isinstance(scope, dict) else None
		if seed is not None:
			if type(seed) is not int or not 0 <= seed < 2_147_483_648:
				raise ValueError("Invalid frozen image seed.")
			return seed
		return int(hashlib.sha256(str(job.generation_run).encode()).hexdigest()[:8], 16) % 2_147_483_648
	scope = frappe.parse_json(
		frappe.db.get_value("Generation Run", job.generation_run, "execution_scope_json") or "{}"
	)
	seed = scope.get("video_seed") if isinstance(scope, dict) else None
	if seed is not None:
		if type(seed) is not int or not 0 <= seed < 2_147_483_648:
			raise ValueError("Invalid frozen video seed.")
		return seed
	return _new_seed()


def _new_seed():
	return secrets.randbelow(2_147_483_648)


@frappe.whitelist()
def retry_finalization(run_name):
	"""Retry processing saved results, without submitting another model job."""
	run = frappe.get_doc("Generation Run", run_name)
	_require_project_generation_authorization(frappe.get_doc("Media Project", run.media_project))
	_require_run_plan_unchanged(run)
	with filelock(f"joymedia-refresh-run-{run.name}"):
		frappe.db.commit()
		run.reload()
		if run.status != "Failed" or run.failure_class != "Finalization":
			frappe.throw(_("Only failed output processing can be resumed."))
		jobs = frappe.get_all(
			"Generation Task", filters={"generation_run": run.name}, fields=["name", "shot", "status"]
		)
		if not jobs or any(row.status != "Completed" for row in jobs):
			frappe.throw(_("Finish the scene generation before retrying its output processing."))
		# A take may already have committed before a later editorial swap failed.
		# Patch only this run's selected output; never override another selection.
		from joymedia.services.editing.timeline import update_timeline_source_for_shot

		for shot in {row.shot for row in jobs}:
			selected = frappe.db.get_value("Shot", shot, "selected_output_asset_version")
			attempt = (
				frappe.db.get_value("Asset Version", selected, "source_generation_attempt")
				if selected
				else None
			)
			task = frappe.db.get_value("Generation Attempt", attempt, "generation_task") if attempt else None
			if task and frappe.db.get_value("Generation Task", task, "generation_run") == run.name:
				update_timeline_source_for_shot(run.media_project, shot)
		run.db_set(
			{"status": "Running", "failure_class": None, "error_summary": None, "completed_at": None},
			update_modified=False,
		)
		frappe.db.commit()
		return _advance_run(run)
