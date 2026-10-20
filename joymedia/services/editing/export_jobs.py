"""The timeline export as a background job: queue it, run it, report its status."""

import frappe
from frappe import _

from joymedia.services.editing.access import (
	_require_project_read,
	_require_project_write,
)
from joymedia.services.project.render_queue import enqueue_render, is_render_alive


@frappe.whitelist()
def queue_project_timeline_export(project_name: str, purpose="review"):
	project = frappe.get_doc("Media Project", project_name)
	_require_project_write(project)
	if purpose not in ("review", "release"):
		raise ValueError("Export purpose must be review or release.")
	if purpose == "release":
		from joymedia.services.review.release import release_evidence
		from joymedia.services.editing.timeline import _timeline_clip_rows

		try:
			release_evidence(project.name, _timeline_clip_rows(project.name))
		except ValueError as exc:
			frappe.throw(str(exc))
	if getattr(project, "export_status", None) in ("Queued", "Running") and is_render_alive(
		_export_job_id(project.name)
	):
		return {
			"status": project.export_status,
			"export_status": project.export_status,
		}
	from joymedia.services.editing.post_production import _job_id as post_production_job_id

	if getattr(project, "post_production_status", None) in ("Queued", "Running") and is_render_alive(
		post_production_job_id(project.name)
	):
		frappe.throw(_("The film is still being finished. Export once the transitions and soundtrack are added."))
	project.db_set("export_status", "Queued")
	project.db_set("export_error", None)
	enqueue_render(
		"joymedia.services.editing.timeline.run_project_timeline_export",
		_export_job_id(project.name),
		# Studio finishing renders every second of film on the GPU.
		timeout=7200,
		project_name=project.name,
		purpose=purpose,
	)
	frappe.db.commit()
	return {
		"status": "Queued",
		"export_status": "Queued",
	}


def _export_job_id(project_name):
	return f"joymedia:export:{project_name}"


def _fail_dead_export(project):
	"""Report an export whose background job died as Failed, so it can be retried."""
	if project.export_status not in ("Queued", "Running") or is_render_alive(_export_job_id(project.name)):
		return
	project.db_set({
		"export_status": "Failed",
		"export_error": _("The export stopped unexpectedly. Please export again."),
		"export_completed_at": frappe.utils.now(),
	})
	frappe.db.commit()


def run_project_timeline_export(project_name: str, purpose="review"):
	project = frappe.get_doc("Media Project", project_name)
	from joymedia.services.editing.export import compose_project_timeline_internal

	try:
		project.db_set("export_status", "Running")
		project.db_set("export_started_at", frappe.utils.now())
		frappe.db.commit()
		result = compose_project_timeline_internal(project.name, require_brand_approval=True) if purpose == "release" else compose_project_timeline_internal(project.name)
		project.db_set("export_status", "Completed")
		project.db_set("export_completed_at", frappe.utils.now())
		frappe.db.commit()
		return result
	except Exception as exc:
		# A failed write aborts the transaction; record the failure in a fresh one.
		frappe.db.rollback()
		project.db_set("export_status", "Failed")
		from joymedia.services.generation.failures import classify_failure, friendly_failure

		# Marketers see a plain message; the technical detail is in the Error Log.
		project.db_set(
			"export_error",
			friendly_failure("Infrastructure")
			if classify_failure(exc) == "Infrastructure"
			else _("The export did not finish. Please export again."),
		)
		project.db_set("export_completed_at", frappe.utils.now())
		frappe.db.commit()
		frappe.log_error(title=f"Timeline export failed for {project_name}")
		raise


@frappe.whitelist()
def get_project_timeline_export_status(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	_require_project_read(project)
	_fail_dead_export(project)
	return {
		"export_status": getattr(project, "export_status", "Idle") or "Idle",
		"export_error": getattr(project, "export_error", None),
		"export_started_at": getattr(project, "export_started_at", None),
		"export_completed_at": getattr(project, "export_completed_at", None),
		"current_output_asset_version": getattr(project, "current_output_asset_version", None),
	}


