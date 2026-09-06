import frappe
from frappe import _
from frappe.utils import now

from .comfyui_client import submit_workflow, upload_frappe_file
from .result_ingestor import sync_attempt_result
from .workflow_resolver import resolve_attempt


@frappe.whitelist()
def submit_attempt_from_ui(attempt_name: str):
	result = submit_attempt(attempt_name)
	frappe.db.commit()
	return {
		"prompt_id": result.get("prompt_id"),
		"result": result,
	}


@frappe.whitelist()
def sync_attempt_result_from_ui(attempt_name: str):
	result = sync_attempt_result(attempt_name)
	frappe.db.commit()
	return result


def prepare_attempt(attempt_name: str):
	"""Resolve an attempt without submitting it to ComfyUI."""
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	job = frappe.get_doc("Generation Job", attempt.generation_job)
	job.validate_for_execution()
	return resolve_attempt(attempt_name)


def prepare_generation_job(job_name: str):
	"""Create a Generation Input snapshot from a Draft job's Shot Input Mapping and mark it Ready."""
	job = frappe.get_doc("Generation Job", job_name)
	if job.status != "Draft":
		frappe.throw(_("Generation Job {0} must be Draft to prepare it.").format(job.name))
	if frappe.db.exists("Generation Attempt", {"generation_job": job.name}):
		frappe.throw(_("Generation Job {0} cannot be prepared after attempts exist.").format(job.name))

	job.validate()
	frappe.db.delete("Generation Input", {"generation_job": job.name})
	for input_role, asset_version in job.get_shot_input_snapshot().items():
		frappe.get_doc(
			{
				"doctype": "Generation Input",
				"generation_job": job.name,
				"asset_version": asset_version,
				"input_role": input_role,
			}
		).insert(ignore_permissions=True)

	job.status = "Ready"
	job.save(ignore_permissions=True)
	return {
		"name": job.name,
		"status": job.status,
		"generation_inputs": frappe.get_all(
			"Generation Input",
			filters={"generation_job": job.name},
			fields=["name", "input_role", "asset_version"],
			order_by="creation asc",
		),
	}


def submit_attempt(attempt_name: str):
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	if attempt.status not in ("Pending", "Failed"):
		frappe.throw(
			_("Attempt {0} cannot be submitted from status {1}.").format(
				attempt.name, attempt.status
			)
		)

	job = frappe.get_doc("Generation Job", attempt.generation_job)
	job.validate_for_execution()
	staged_inputs = _stage_generation_inputs(job)
	workflow = resolve_attempt(attempt.name, staged_inputs=staged_inputs)
	attempt.reload()
	result = submit_workflow(workflow)

	attempt.external_job_id = result["prompt_id"]
	attempt.status = "Queued"
	attempt.queued_at = now()
	attempt.save(ignore_permissions=True)
	return result


def _stage_generation_inputs(job):
	rows = frappe.get_all(
		"Generation Input",
		filters={"generation_job": job.name},
		fields=["name", "asset_version", "input_role"],
		order_by="creation asc",
	)
	if not rows:
		frappe.throw(_("Generation Job {0} has no Generation Inputs.").format(job.name))

	staged = {}
	for row in rows:
		asset_version = frappe.get_doc("Asset Version", row.asset_version)
		if not asset_version.file:
			frappe.throw(_("Asset Version {0} has no file.").format(asset_version.name))
		uploaded = upload_frappe_file(asset_version.file)
		staged[row.input_role] = uploaded["server_path"]
	return staged
