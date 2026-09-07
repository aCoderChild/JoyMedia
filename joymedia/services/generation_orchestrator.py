import secrets

import frappe
from frappe import _
from frappe.utils import now

from joymedia.joymedia.doctype.generation_attempt.generation_attempt import create_retry_attempt

from .generation_runner import prepare_generation_job, submit_attempt
from .prompt_compiler import compile_prompt
from .result_ingestor import sync_attempt_result
from .video_composer import compose_media_specification


ACTIVE_RUN_STATUSES = ("Queued", "Running")
ACTIVE_ATTEMPT_STATUSES = ("Pending", "Queued", "Running")
TERMINAL_ATTEMPT_STATUSES = ("Completed", "Failed", "Cancelled")
TERMINAL_JOB_STATUSES = ("Completed", "Partially Completed", "Failed", "Cancelled")


@frappe.whitelist()
def start_run(run_name: str):
	"""Start a Draft Generation Run and hand the remaining workflow to background jobs."""
	frappe.has_permission("Generation Run", "write", run_name, throw=True)
	run = frappe.get_doc("Generation Run", run_name)
	if run.status != "Draft":
		frappe.throw(_("Generation Run {0} must be Draft to start.").format(run.name))

	media_specification = frappe.get_doc("Media Specification", run.media_specification)
	if media_specification.status != "Ready":
		frappe.throw(_("Media Specification {0} must be Ready to start a Generation Run.").format(media_specification.name))

	run.status = "Queued"
	run.queued_at = now()
	run.error_summary = None
	run.save(ignore_permissions=True)
	_enqueue("prepare_run", run.name)
	return {"name": run.name, "status": run.status}


def prepare_run(run_name: str):
	"""Create one Job and frozen Generation Input snapshot for each Shot in a run."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status == "Cancelled":
		return _run_summary(run)
	if run.status not in ACTIVE_RUN_STATUSES:
		frappe.throw(_("Generation Run {0} cannot be prepared from status {1}.").format(run.name, run.status))

	media_specification = frappe.get_doc("Media Specification", run.media_specification)
	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_specification.name},
		fields=["name"],
		order_by="shot_number asc, name asc",
	)
	if not shots:
		_raise_run_error(run, _("Media Specification {0} has no Shot Specifications.").format(media_specification.name))
		return _run_summary(run)

	try:
		for shot in shots:
			if frappe.db.exists(
				"Generation Job", {"generation_run": run.name, "shot_specification": shot.name}
			):
				continue

			compiled_prompt = compile_prompt(shot.name, media_specification.prompt_template_version)
			job = frappe.get_doc(
				{
					"doctype": "Generation Job",
					"generation_run": run.name,
					"shot_specification": shot.name,
					"workflow_version": run.workflow_version,
					"compiled_prompt": compiled_prompt.name,
					"requested_by": run.requested_by,
					"requested_variants": run.requested_variants_per_shot,
					"status": "Draft",
				}
			).insert(ignore_permissions=True)
			prepare_generation_job(job.name)
	except Exception as exc:
		_raise_run_error(run, str(exc))
		return _run_summary(run)

	_refresh_run_counters(run)
	_enqueue("submit_run", run.name)
	return _run_summary(run)


def submit_run(run_name: str):
	"""Create and submit outstanding attempts for prepared Jobs in this run."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status == "Cancelled":
		return _run_summary(run)
	if run.status not in ACTIVE_RUN_STATUSES:
		return _run_summary(run)

	run.status = "Running"
	if not run.started_at:
		run.started_at = now()
	run.save(ignore_permissions=True)

	for job_name in _get_run_job_names(run.name):
		job = frappe.get_doc("Generation Job", job_name)
		if job.status in ("Completed", "Partially Completed", "Failed", "Cancelled", "Running"):
			continue

		if job.status == "Ready":
			job.status = "Queued"
			job.queued_at = now()
			job.save(ignore_permissions=True)

		if job.status != "Queued":
			continue

		for attempt_name in _create_initial_attempts(job):
			_submit_attempt_or_record_failure(attempt_name)

		for attempt_name in _get_pending_attempt_names(job.name):
			_submit_attempt_or_record_failure(attempt_name)

	return refresh_run(run.name)


def refresh_run(run_name: str, enqueue_finalization: bool = True):
	"""Refresh attempt state, aggregate Job counters, and advance the Run lifecycle."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status == "Cancelled":
		return _run_summary(run)

	for attempt_name in _get_active_attempt_names(run.name):
		try:
			sync_attempt_result(attempt_name)
		except Exception:
			frappe.logger("joymedia.generation_run").exception(
				"Unable to refresh Generation Attempt %s for Run %s", attempt_name, run.name
			)

	jobs = [frappe.get_doc("Generation Job", job_name) for job_name in _get_run_job_names(run.name)]
	for job in jobs:
		_update_job_summary(job)

	if _create_retry_attempt(run, jobs) or _get_pending_attempt_names_for_run(run.name):
		_enqueue("submit_run", run.name)

	_refresh_run_counters(run)
	if enqueue_finalization:
		_enqueue_finalization_if_ready(run)
	return _run_summary(run)


def refresh_generation_state_for_attempt(attempt_name: str):
	"""Derive the parent Job and Run state after an Attempt state change."""
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	job = frappe.get_doc("Generation Job", attempt.generation_job)
	_update_job_summary(job)
	if not job.generation_run:
		return {"generation_job": job.name, "job_status": job.status}

	run = frappe.get_doc("Generation Run", job.generation_run)
	if run.status == "Cancelled":
		return _run_summary(run)
	_refresh_run_counters(run)
	_enqueue_finalization_if_ready(run)
	return _run_summary(run)


def enqueue_finalization_if_ready(run_name: str):
	"""Queue final composition only after completed Jobs have approved selected outputs."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status != "Cancelled":
		_refresh_run_counters(run)
		_enqueue_finalization_if_ready(run)
	return _run_summary(run)


def finalize_run(run_name: str):
	"""Compose a completed run's selected outputs into its final Asset Version."""
	run = frappe.get_doc("Generation Run", run_name)
	refresh_run(run.name, enqueue_finalization=False)
	run.reload()
	if run.status != "Completed":
		frappe.throw(_("Generation Run {0} must complete before finalization.").format(run.name))
	if run.final_asset_version:
		return _run_summary(run)

	try:
		result = compose_media_specification(run.media_specification)
	except Exception as exc:
		_raise_run_error(run, str(exc))
		return _run_summary(run)

	run.final_asset_version = result["final_asset_version"]
	run.save(ignore_permissions=True)
	return _run_summary(run)


def cancel_run(run_name: str):
	"""Stop orchestration and cancel only attempts that have not reached ComfyUI."""
	run = frappe.get_doc("Generation Run", run_name)
	if run.status in ("Completed", "Partially Completed", "Failed", "Cancelled"):
		return _run_summary(run)

	for attempt_name in _get_pending_attempt_names_for_run(run.name):
		attempt = frappe.get_doc("Generation Attempt", attempt_name)
		if not attempt.external_job_id:
			attempt.status = "Cancelled"
			attempt.save(ignore_permissions=True)

	run.status = "Cancelled"
	run.completed_at = now()
	run.save(ignore_permissions=True)
	return _run_summary(run)


def refresh_active_runs():
	"""Scheduler entry point for all active runs."""
	for run_name in frappe.get_all(
		"Generation Run", filters={"status": ["in", ACTIVE_RUN_STATUSES]}, pluck="name"
	):
		try:
			refresh_run(run_name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.logger("joymedia.generation_run").exception(
				"Unable to refresh Generation Run %s", run_name
			)


def _create_initial_attempts(job):
	attempts = _get_job_attempts(job.name)
	initial_attempts = [attempt for attempt in attempts if not attempt.retry_of]
	created = []
	for _ in range(max(0, job.requested_variants - len(initial_attempts))):
		attempt = frappe.get_doc(
			{
				"doctype": "Generation Attempt",
				"generation_job": job.name,
				"seed": _new_seed(),
				"status": "Pending",
			}
		).insert(ignore_permissions=True)
		created.append(attempt.name)
	return created


def _create_retry_attempt(run, jobs):
	if not run.max_retries:
		return False

	for job in jobs:
		attempts = _get_job_attempts(job.name)
		successful_attempts = [attempt for attempt in attempts if attempt.status == "Completed"]
		active_attempts = [attempt for attempt in attempts if attempt.status in ACTIVE_ATTEMPT_STATUSES]
		retry_attempts = [attempt for attempt in attempts if attempt.retry_of]
		failed_attempts = [attempt for attempt in attempts if attempt.status == "Failed"]
		if (
			len(successful_attempts) >= job.requested_variants
			or active_attempts
			or not failed_attempts
			or len(retry_attempts) >= run.max_retries
		):
			continue

		job.status = "Queued"
		job.queued_at = now()
		job.save(ignore_permissions=True)
		create_retry_attempt(failed_attempts[-1].name, "Execution Failure")
		return True
	return False


def _submit_attempt_or_record_failure(attempt_name):
	try:
		submit_attempt(attempt_name)
	except Exception as exc:
		attempt = frappe.get_doc("Generation Attempt", attempt_name)
		if attempt.status == "Pending":
			attempt.status = "Failed"
			attempt.error_summary = _("Submission to ComfyUI failed.")
			attempt.error_details = str(exc)
			attempt.save(ignore_permissions=True)


def _update_job_summary(job):
	attempts = _get_job_attempts(job.name)
	successful_variants = sum(attempt.status == "Completed" for attempt in attempts)
	failed_variants = sum(attempt.status == "Failed" for attempt in attempts)
	statuses = {attempt.status for attempt in attempts}

	job.successful_variants = successful_variants
	job.failed_variants = failed_variants
	job.progress = min(100, round(successful_variants / job.requested_variants * 100, 2))
	if successful_variants >= job.requested_variants:
		job.status = "Completed"
		job.completed_at = job.completed_at or now()
		job.error_summary = None
	elif "Running" in statuses:
		job.status = "Running"
		job.started_at = job.started_at or now()
	elif statuses & {"Pending", "Queued"}:
		job.status = "Queued"
	elif attempts and statuses <= set(TERMINAL_ATTEMPT_STATUSES):
		job.status = "Partially Completed" if successful_variants else "Failed"
		job.completed_at = job.completed_at or now()
		job.error_summary = _("Only {0} of {1} requested variants completed.").format(
			successful_variants, job.requested_variants
		)
	job.save(ignore_permissions=True)


def _refresh_run_counters(run):
	jobs = frappe.get_all(
		"Generation Job",
		filters={"generation_run": run.name},
		fields=["status"],
	)
	run.total_jobs = len(jobs)
	run.completed_jobs = sum(job.status == "Completed" for job in jobs)
	run.failed_jobs = sum(job.status == "Failed" for job in jobs)
	run.running_jobs = sum(job.status == "Running" for job in jobs)
	run.progress = round(run.completed_jobs / run.total_jobs * 100, 2) if run.total_jobs else 0

	terminal_jobs = sum(job.status in TERMINAL_JOB_STATUSES for job in jobs)
	partially_completed_jobs = sum(job.status == "Partially Completed" for job in jobs)
	if run.total_jobs and run.completed_jobs == run.total_jobs:
		run.status = "Completed"
		run.completed_at = run.completed_at or now()
	elif run.total_jobs and terminal_jobs == run.total_jobs:
		run.status = "Partially Completed" if run.completed_jobs or partially_completed_jobs else "Failed"
		run.completed_at = run.completed_at or now()
	elif run.total_jobs and any(job.status in ("Ready", "Queued", "Running") for job in jobs):
		run.status = "Running"
	run.save(ignore_permissions=True)


def _enqueue_finalization_if_ready(run):
	if (
		run.status != "Completed"
		or not run.auto_compose
		or run.final_asset_version
		or not _run_outputs_are_selected(run.name)
	):
		return
	_enqueue("finalize_run", run.name)


def _run_outputs_are_selected(run_name):
	for job in frappe.get_all(
		"Generation Job",
		filters={"generation_run": run_name},
		fields=["shot_specification"],
	):
		if not frappe.db.get_value("Shot Specification", job.shot_specification, "selected_output_asset_version"):
			return False
	return True


def _get_run_job_names(run_name):
	return frappe.get_all(
		"Generation Job",
		filters={"generation_run": run_name},
		pluck="name",
		order_by="creation asc",
	)


def _get_job_attempts(job_name):
	return frappe.get_all(
		"Generation Attempt",
		filters={"generation_job": job_name},
		fields=["name", "status", "retry_of"],
		order_by="attempt_number asc, creation asc",
	)


def _get_pending_attempt_names(job_name):
	return frappe.get_all(
		"Generation Attempt",
		filters={"generation_job": job_name, "status": "Pending"},
		pluck="name",
		order_by="attempt_number asc, creation asc",
	)


def _get_active_attempt_names(run_name):
	job_names = _get_run_job_names(run_name)
	if not job_names:
		return []
	return frappe.get_all(
		"Generation Attempt",
		filters={"generation_job": ["in", job_names], "status": ["in", ["Queued", "Running"]]},
		pluck="name",
	)


def _get_pending_attempt_names_for_run(run_name):
	job_names = _get_run_job_names(run_name)
	if not job_names:
		return []
	return frappe.get_all(
		"Generation Attempt",
		filters={"generation_job": ["in", job_names], "status": "Pending"},
		pluck="name",
	)


def _enqueue(method_name, run_name):
	frappe.enqueue(
		f"joymedia.services.generation_orchestrator.{method_name}",
		queue="long",
		run_name=run_name,
		enqueue_after_commit=True,
	)


def _raise_run_error(run, message):
	run.status = "Failed"
	run.error_summary = message
	run.completed_at = now()
	run.save(ignore_permissions=True)


def _run_summary(run):
	return {
		"name": run.name,
		"status": run.status,
		"total_jobs": run.total_jobs,
		"completed_jobs": run.completed_jobs,
		"failed_jobs": run.failed_jobs,
		"running_jobs": run.running_jobs,
		"progress": run.progress,
		"final_asset_version": run.final_asset_version,
	}


def _new_seed():
	return secrets.randbelow(2_147_483_648)
