import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now
from frappe.utils.synchronization import filelock

from .artifact_service import get_attempt_artifact
from .comfyui_client import get_base_url, submit_workflow, upload_frappe_file
from .prompt_compiler import compile_prompt
from .result_ingestor import sync_attempt_result
from .workflow_resolver import resolve_attempt
from joymedia.joymedia.doctype.generation_attempt.generation_attempt import get_effective_attempt


def submit_attempt_from_ui(attempt_name: str):
	result = submit_attempt(attempt_name)
	frappe.db.commit()
	return {"prompt_id": result.get("prompt_id"), "result": result}


def sync_attempt_result_from_ui(attempt_name: str):
	result = sync_attempt_result(attempt_name)
	frappe.db.commit()
	return result


def prepare_attempt(attempt_name: str):
	"""Resolve an attempt without submitting it to ComfyUI."""
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	job = frappe.get_doc("Generation Task", attempt.generation_task)
	job.validate_for_execution()
	return resolve_attempt(attempt_name)


def prepare_generation_task(job_name: str, input_snapshot=None):
	"""Freeze the supplied snapshot onto its Generation Task."""
	job = frappe.get_doc("Generation Task", job_name)
	if job.status != "Draft":
		frappe.throw(_("Generation Task {0} must be Draft to prepare it.").format(job.name))
	if frappe.db.exists("Generation Attempt", {"generation_task": job.name}):
		frappe.throw(_("Generation Task {0} cannot be prepared after attempts exist.").format(job.name))

	job.validate()
	job.set("inputs", [])
	snapshot = input_snapshot
	if snapshot is None:
		snapshot = job.get_shot_input_snapshot()
	else:
		grouped = {}
		for row in snapshot:
			if row.get("reference_role") and row.get("asset_version"):
				grouped.setdefault(frappe.scrub(row["reference_role"]), []).append(row["asset_version"])
		snapshot = grouped
	if job.depends_on_task:
		# Continuation is runtime lineage and is resolved from the upstream Attempt,
		# rather than persisted as if it were a reusable project asset.
		snapshot.pop("first_frame", None)
	for input_role, asset_versions in snapshot.items():
		for asset_version in asset_versions if isinstance(asset_versions, list) else [asset_versions]:
			job.append("inputs", {"input_role": input_role, "asset_version": asset_version})
	job.inputs_frozen = 1
	job.status = "Ready"
	job.save(ignore_permissions=True)
	return {
		"name": job.name,
		"status": job.status,
		"inputs": [
			{"input_role": row.input_role, "asset_version": row.asset_version}
			for row in job.inputs
		],
	}


def attach_chained_first_frame(job):
	"""Return whether a chained task has an upstream Last Frame Artifact available."""
	if not job.depends_on_task:
		return True
	previous_attempt = get_effective_attempt(job.depends_on_task)
	if not previous_attempt or previous_attempt.status != "Completed":
		return False
	return bool(get_attempt_artifact(previous_attempt.name, "Last Frame"))


def ensure_generation_inputs(job):
	"""Ensure the Job owns its frozen static input snapshot."""
	if not isinstance(job, Document):
		return False
	if job.inputs_frozen:
		return True
	if job.get("inputs"):
		job.inputs_frozen = 1
		job.save(ignore_permissions=True)
		return True
	if job.depends_on_task:
		# A continuation task may intentionally have no static inputs; its first
		# frame is resolved from the dependency at attempt submission time.
		job.inputs_frozen = 1
		job.save(ignore_permissions=True)
		return True
	if frappe.db.exists("Generation Attempt", {"generation_task": job.name}):
		frappe.throw(
			_("Generation Task {0} has execution history but no frozen input snapshot.").format(job.name)
		)

	snapshot = job.get_shot_input_snapshot()
	if job.depends_on_task:
		snapshot.pop("first_frame", None)
	for input_role, asset_versions in snapshot.items():
		for asset_version in asset_versions if isinstance(asset_versions, list) else [asset_versions]:
			job.append("inputs", {"input_role": input_role, "asset_version": asset_version})
	job.inputs_frozen = 1
	job.save(ignore_permissions=True)
	return True


def _autosave_prompt_snapshot(job):
	"""Fill missing prompt snapshot fields once; retries reuse the same Job prompt."""
	if not isinstance(job, Document):
		return
	if not job.prompt_text:
		prompt_text = compile_prompt(job.shot)
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
				_("Attempt {0} cannot be submitted from status {1}.").format(attempt.name, attempt.status)
			)

		job = frappe.get_doc("Generation Task", attempt.generation_task)
		if job.depends_on_task and not attach_chained_first_frame(job):
			return {"deferred": True, "dependency": job.depends_on_task}

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
		attempt.external_job_id = result["prompt_id"]
		attempt.status = "Queued"
		attempt.queued_at = now()
		attempt.save(ignore_permissions=True)
		return result


def _stage_generation_inputs(job, attempt):
	"""Upload frozen Job inputs and resolve dynamic continuation for this Attempt."""
	staged = {}
	resolved_inputs = {}
	for row in job.get("inputs") or []:
		role = frappe.scrub(row.input_role or "")
		if row.generation_artifact:
			file_url = frappe.db.get_value("Generation Artifact", row.generation_artifact, "frappe_file")
			if not file_url:
				frappe.throw(_("Generation Artifact {0} has no file.").format(row.generation_artifact))
			resolved_inputs.setdefault(role, []).append({"source": "Generation Artifact", "artifact": row.generation_artifact})
		else:
			asset_version = frappe.get_doc("Asset Version", row.asset_version)
			file_url = asset_version.file
			resolved_inputs.setdefault(role, []).append({"source": "Asset Version", "asset_version": row.asset_version})
		if not file_url:
			frappe.throw(_("Generation input role {0} has no file.").format(role))
		staged.setdefault(role, []).append(upload_frappe_file(file_url)["server_path"])

	if job.depends_on_task:
		previous_attempt = get_effective_attempt(job.depends_on_task)
		if not previous_attempt or previous_attempt.status != "Completed":
			frappe.throw(_("A chained Generation Task requires a completed upstream Attempt."))
		last_frame_artifact = get_attempt_artifact(previous_attempt.name, "Last Frame")
		if not last_frame_artifact or not last_frame_artifact.frappe_file:
			frappe.throw(_("The upstream Attempt has no usable Last Frame Artifact."))
		staged["first_frame"] = [upload_frappe_file(last_frame_artifact.frappe_file)["server_path"]]
		resolved_inputs["first_frame"] = [{
			"source": "Generation Artifact",
			"artifact": last_frame_artifact.name,
		}]

	if not staged:
		frappe.throw(_("Generation Task {0} has no resolved inputs.").format(job.name))

	attempt.resolved_inputs_json = json.dumps(resolved_inputs, sort_keys=True)
	attempt.save(ignore_permissions=True)
	return staged
