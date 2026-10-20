"""Bookkeeping of a Generation Run: its counters and summary, project status sync, error recording and background enqueueing."""

import frappe
from frappe import _
from frappe.utils import now

ACTIVE_RUN_STATUSES = ("Queued", "Running")


def sync_media_project_status_for_run(run_name: str):
	"""Derive the customer-facing Campaign status from its generation state."""
	run = frappe.get_doc("Generation Run", run_name)
	media_project = run.media_project
	if not media_project:
		return
	if frappe.db.get_value("Media Project", media_project, "status") == "Archived":
		return
	latest = frappe.get_all(
		"Generation Run",
		filters={"media_project": media_project},
		fields=["name", "status"],
		order_by="creation desc",
		limit_page_length=1,
	)
	if not latest:
		status = "Draft"
	elif latest[0].status in ACTIVE_RUN_STATUSES or frappe.db.exists(
		# Several scenes may be regenerating in separate runs.
		"Generation Run",
		{"media_project": media_project, "status": ["in", ACTIVE_RUN_STATUSES]},
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

	if run.status == "Cancelled" or (run.status == "Failed" and run.failure_class == "Finalization"):
		run.running_tasks = 0
	elif run.total_tasks and run.completed_tasks == run.total_tasks:
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
			(job for job in reversed(jobs) if job.status == "Failed" and job.error_summary),
			None,
		)
		run.failure_class = latest_failed_job.failure_class if latest_failed_job else None
		run.error_summary = (
			"Some scenes need attention while other scenes are still rendering."
			if active_tasks
			else latest_failed_job.error_summary
			if latest_failed_job
			else None
		)
	elif run.total_tasks and any(job.status == "Running" for job in jobs):
		run.status = "Running"
		run.failure_class = None
		run.error_summary = None
	elif run.total_tasks and any(job.status in ("Ready", "Queued") for job in jobs):
		run.status = "Queued"
		run.failure_class = None
		run.error_summary = None
	# Cancellation is durable user intent. A poll that began before Stop may
	# derive Running from its old snapshot, but cannot overwrite Cancelled in SQL.
	values = {
		"total_tasks": run.total_tasks,
		"completed_tasks": run.completed_tasks,
		"failed_tasks": run.failed_tasks,
		"running_tasks": run.running_tasks,
		"progress": run.progress,
	}
	if run.status == "Cancelled":
		filters = {"name": run.name, "status": "Cancelled"}
	else:
		filters = {"name": run.name, "status": ["!=", "Cancelled"]}
		values.update(
			status=run.status,
			completed_at=run.completed_at,
			failure_class=run.failure_class,
			error_summary=run.error_summary,
		)
	frappe.db.set_value("Generation Run", filters, values, update_modified=False)


def _is_keyframe_run(run):
	try:
		return (frappe.parse_json(run.execution_scope_json or "{}") or {}).get("stage") == "keyframe"
	except (TypeError, ValueError, AttributeError):
		return False


def _run_outputs_are_selected(run_name):
	if _is_keyframe_run(frappe.get_doc("Generation Run", run_name)):
		return True  # a keyframe run selects no video
	run = frappe.get_doc("Generation Run", run_name)
	from joymedia.services.consistency.retention import needs_candidate_review

	snapshot = frappe.parse_json(run.project_snapshot_json or "{}") or {}
	scenes = {row.get("shot"): row for row in snapshot.get("shots", [])}
	scope = frappe.parse_json(run.execution_scope_json or "{}") or {}
	seen_candidates = set()
	for job in frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name},
		fields=["name", "shot", "workflow", "segment_index"],
		order_by="segment_index desc, creation desc",
	):
		if scope.get("candidate_only") or needs_candidate_review(scenes.get(job.shot, {})):
			if frappe.db.get_value("Generation Workflow", job.workflow, "output_media_type") != "Video":
				continue
			if job.shot in seen_candidates:
				continue
			seen_candidates.add(job.shot)
			attempt = frappe.db.get_value(
				"Generation Attempt",
				{"generation_task": job.name, "status": "Completed"},
				"name",
				order_by="creation desc",
			)
			if not attempt or not frappe.db.exists(
				"Asset Version", {"source_generation_attempt": attempt, "source": "Composed"}
			):
				return False
			continue
		if not frappe.db.get_value("Shot", job.shot, "selected_output_asset_version"):
			return False
	return True


def _get_run_job_names(run_name):
	return frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name},
		pluck="name",
		order_by="creation asc",
	)


def _enqueue(method_name, run_name):
	frappe.enqueue(
		f"joymedia.services.generation.orchestrator.{method_name}",
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
		"joymedia.services.generation.orchestrator.submit_run",
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
