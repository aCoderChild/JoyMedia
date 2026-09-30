import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now
from frappe.utils.synchronization import filelock

from .comfyui_client import get_base_url, submit_workflow, upload_frappe_file
from .result_ingestor import sync_attempt_result
from .artifact_service import get_attempt_artifact
from joymedia.joymedia.doctype.generation_attempt.generation_attempt import get_effective_attempt
from .prompt_compiler import compile_prompt
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
	snapshot = job.get_shot_input_snapshot()
	if job.depends_on_job:
		# Continuous first frames are attached immediately before submission from the
		# previous job's generated last-frame Asset Version.
		snapshot.pop("first_frame", None)
	for input_role, asset_version in snapshot.items():
		frappe.get_doc(
			{
				"doctype": "Generation Input",
				"generation_job": job.name,
				"asset_version": asset_version,
				"input_role": input_role,
			}
		).insert(ignore_permissions=True)

	if job.depends_on_job:
		job.db_set("status", "Ready", update_modified=False)
	else:
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


def attach_chained_first_frame(job):
	"""Check that a chained job has an upstream Last Frame Artifact available."""
	if not job.depends_on_job:
		return True

	previous_attempt = get_effective_attempt(job.depends_on_job)
	if not previous_attempt or previous_attempt.status != "Completed":
		return False
	last_frame_artifact = get_attempt_artifact(previous_attempt.name, "Last Frame")
	return bool(last_frame_artifact)


def ensure_generation_inputs(job):
	"""Materialize the immutable input snapshot required before execution.

	Jobs created by older flows may reach submission without a Generation Input
	snapshot. Rebuild it from the Shot Specification exactly once; never replace
	an existing snapshot during a retry.
	"""
	if not isinstance(job, Document):
		return False

	rows = frappe.get_all(
		"Generation Input",
		filters={"generation_job": job.name},
		fields=["input_role", "asset_version"],
	)
	if not rows:
		snapshot = job.get_shot_input_snapshot()
		if job.depends_on_job:
			# The chained first frame is runtime lineage, not a Shot Input Mapping.
			snapshot.pop("first_frame", None)
		for input_role, asset_version in snapshot.items():
			frappe.get_doc(
				{
					"doctype": "Generation Input",
					"generation_job": job.name,
					"asset_version": asset_version,
					"input_role": input_role,
				}
			).insert(ignore_permissions=True)

	if job.depends_on_job and not attach_chained_first_frame(job):
		frappe.throw(
			_(
				"Generation Job {0} cannot run until its previous chained shot has a last frame."
			).format(job.name)
		)
	return True


def _autosave_prompt_snapshot(job):
	"""Fill missing prompt snapshot fields from the Shot Specification.

	An existing prompt is authoritative and is never recompiled on retry.
	"""
	if not isinstance(job, Document):
		return
	if not job.prompt_text:
		prompt_text = compile_prompt(job.shot_specification)
		job.db_set("prompt_text", prompt_text, update_modified=False)
		job.prompt_text = prompt_text
	if not job.prompt_hash:
		prompt_hash = hashlib.sha256(job.prompt_text.encode("utf-8")).hexdigest()
		job.db_set("prompt_hash", prompt_hash, update_modified=False)
		job.prompt_hash = prompt_hash


def submit_attempt(attempt_name: str):
	with filelock(f"joymedia-submit-attempt-{attempt_name}"):
		attempt = frappe.get_doc("Generation Attempt", attempt_name)
		if attempt.status != "Pending":
			frappe.throw(
				_("Attempt {0} cannot be submitted from status {1}.").format(
					attempt.name, attempt.status
				)
			)

		job = frappe.get_doc("Generation Job", attempt.generation_job)
		_autosave_prompt_snapshot(job)
		ensure_generation_inputs(job)
		job.reload()
		job.validate_for_execution()
		staged_inputs = _stage_generation_inputs(job, attempt)
		workflow = resolve_attempt(attempt.name, staged_inputs=staged_inputs)
		attempt.reload()
		endpoint_url = get_base_url()
		result = submit_workflow(workflow, base_url=endpoint_url)

		attempt.comfyui_endpoint_url = endpoint_url
		backend_name = frappe.db.get_value(
			"Generation Backend",
			{"endpoint_url": endpoint_url, "enabled": 1},
			"name",
		)
		if backend_name:
			attempt.generation_backend = backend_name
		attempt.external_job_id = result["prompt_id"]
		attempt.status = "Queued"
		attempt.queued_at = now()
		attempt.save(ignore_permissions=True)
		return result


def _stage_generation_inputs(job, attempt):
	rows = frappe.get_all(
		"Generation Input",
		filters={"generation_job": job.name},
		fields=["name", "asset_version", "generation_artifact", "input_role"],
		order_by="creation asc",
	)
	if not rows:
		frappe.throw(_("Generation Job {0} has no Generation Inputs.").format(job.name))

	staged = {}
	resolved_inputs = {}
	for row in rows:
		file_url = None
		if row.generation_artifact:
			file_url = frappe.db.get_value("Generation Artifact", row.generation_artifact, "frappe_file")
			if not file_url:
				frappe.throw(_("Generation Artifact {0} has no file.").format(row.generation_artifact))
			resolved_inputs[frappe.scrub(row.input_role)] = {
				"source": "Generation Artifact",
				"artifact": row.generation_artifact,
			}
		else:
			asset_version = frappe.get_doc("Asset Version", row.asset_version)
			file_url = asset_version.file
			resolved_inputs.setdefault(
				frappe.scrub(row.input_role),
				{"source": "Asset Version", "asset_version": row.asset_version},
			)
		if not file_url:
			frappe.throw(_("Generation input {0} has no file.").format(row.name))
		uploaded = upload_frappe_file(
			file_url,
		)
		role = frappe.scrub(row.input_role or "")
		staged[role] = uploaded["server_path"]

	if job.depends_on_job:
		previous_attempt = get_effective_attempt(job.depends_on_job)
		if not previous_attempt or previous_attempt.status != "Completed":
			frappe.throw(_("A chained Generation Job requires a completed upstream Attempt."))
		last_frame_artifact = get_attempt_artifact(previous_attempt.name, "Last Frame")
		if not last_frame_artifact:
			frappe.throw(_("The upstream Attempt has no Last Frame Artifact."))
		file_url = last_frame_artifact.frappe_file
		if not file_url:
			frappe.throw(_("Last Frame Artifact {0} has no file.").format(last_frame_artifact.name))
		uploaded = upload_frappe_file(file_url)
		staged["first_frame"] = uploaded["server_path"]
		resolved_inputs["first_frame"] = {
			"source": "Generation Artifact",
			"artifact": last_frame_artifact.name,
		}

	attempt.resolved_inputs_json = json.dumps(resolved_inputs, sort_keys=True)
	attempt.save(ignore_permissions=True)
	return staged
