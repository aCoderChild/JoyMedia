import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now
from frappe.utils.synchronization import filelock

from .artifact_service import get_attempt_artifact
from .comfyui_client import (
	find_prompt_by_client_id,
	get_base_url,
	submit_workflow,
	upload_frappe_file,
	upload_local_file,
)
from .prompt_compiler import compile_prompt
from .reference_compositor import compose_reference_board
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
	"""Backward-compatible readiness check for chained task inputs."""
	return attach_chained_inputs(job)


def attach_chained_inputs(job):
	"""Return whether a chained task has the artifacts required by its workflow."""
	if not job.depends_on_task:
		return True
	previous_attempt = get_effective_attempt(job.depends_on_task)
	if not previous_attempt or previous_attempt.status != "Completed":
		return False
	workflow = frappe.get_doc("Generation Workflow", job.workflow)
	if job.dependency_artifact_role:
		artifact = get_attempt_artifact(previous_attempt.name, job.dependency_artifact_role)
		return bool(artifact and artifact.frappe_file)
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
		if attempt.status == "Submitting":
			return reconcile_attempt_submission(attempt.name)
		if attempt.status != "Pending":
			frappe.throw(
				_("Attempt {0} cannot be submitted from status {1}.").format(attempt.name, attempt.status)
			)

		job = frappe.get_doc("Generation Task", attempt.generation_task)
		if job.depends_on_task and not attach_chained_inputs(job):
			return {"deferred": True, "dependency": job.depends_on_task}

		_autosave_prompt_snapshot(job)
		ensure_generation_inputs(job)
		job.reload()
		job.validate_for_execution()
		# Persist the identity before the network call. A process crash after
		# ComfyUI accepts the prompt can then be reconciled without resubmitting.
		attempt.submission_token = attempt.submission_token or f"joymedia:{attempt.name}"
		attempt.comfyui_endpoint_url = get_base_url()
		attempt.submission_state = "Submitting"
		attempt.status = "Submitting"
		attempt.save(ignore_permissions=True)
		frappe.db.commit()

		staged_inputs = _stage_generation_inputs(job, attempt)
		workflow = resolve_attempt(attempt.name, staged_inputs=staged_inputs)
		attempt.reload()
		endpoint_url = attempt.comfyui_endpoint_url
		result = submit_workflow(workflow, base_url=endpoint_url, client_id=attempt.submission_token)

		attempt.external_job_id = result["prompt_id"]
		attempt.submission_state = "Submitted"
		attempt.status = "Queued"
		attempt.queued_at = now()
		attempt.save(ignore_permissions=True)
		return result


def reconcile_attempt_submission(attempt_name: str):
	"""Associate an interrupted submission with ComfyUI without duplicate work."""
	with filelock(f"joymedia-submit-attempt-{attempt_name}"):
		attempt = frappe.get_doc("Generation Attempt", attempt_name)
		if attempt.status != "Submitting":
			return {"status": attempt.status, "prompt_id": attempt.external_job_id}
		if not attempt.submission_token or not attempt.comfyui_endpoint_url:
			frappe.throw(_("Submitting Attempt {0} has no durable submission identity.").format(attempt.name))
		prompt_id = find_prompt_by_client_id(
			attempt.submission_token, base_url=attempt.comfyui_endpoint_url
		)
		if not prompt_id:
			return {"reconciling": True, "submission_token": attempt.submission_token}
		attempt.external_job_id = prompt_id
		attempt.submission_state = "Submitted"
		attempt.status = "Queued"
		attempt.queued_at = attempt.queued_at or now()
		attempt.save(ignore_permissions=True)
		return {"prompt_id": prompt_id, "reconciled": True}


def _stage_generation_inputs(job, attempt):
	"""Upload frozen Job inputs and resolve dynamic continuation for this Attempt."""
	staged = {}
	resolved_inputs = {}
	workflow = frappe.get_doc("Generation Workflow", job.workflow)
	compose_roles = _reference_composition_roles(workflow)
	composed_references = {}
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
		if role in compose_roles:
			file_doc = frappe.get_doc("File", {"file_url": file_url})
			composed_references.setdefault(role, []).append({
				"path": file_doc.get_full_path(),
				"role": _reference_role_for_task_asset(job, row.asset_version),
				"label": _reference_label_for_task_asset(job, row.asset_version),
				"asset_version": row.asset_version,
			})
			continue
		staged.setdefault(role, []).append(upload_frappe_file(file_url)["server_path"])

	for role, references in composed_references.items():
		if len(references) == 1:
			reference = references[0]
			staged[role] = [upload_local_file(reference["path"])["server_path"]]
			resolved_inputs[role] = [{
				"source": "Asset Version",
				"asset_version": reference["asset_version"],
				"reference_role": reference["role"],
			}]
			continue
		run = frappe.get_doc("Generation Run", job.generation_run)
		try:
			snapshot = frappe.parse_json(run.project_snapshot_json or "{}")
		except (TypeError, ValueError):
			snapshot = {}
		board = compose_reference_board(
			references,
			width=int(snapshot.get("delivery_width") or 1344),
			height=int(snapshot.get("delivery_height") or 768),
		)
		uploaded = upload_local_file(board["path"])
		staged[role] = [uploaded["server_path"]]
		staged[f"{role}_instruction"] = board["instruction"]
		resolved_inputs[role] = [{
			"source": "Reference Board",
			"asset_version": reference["asset_version"],
			"reference_role": reference["role"],
			"label": reference["label"],
		} for reference in references]
		resolved_inputs[f"{role}_board"] = {"sha256": board["sha256"], "count": board["count"]}

	if job.depends_on_task:
		previous_attempt = get_effective_attempt(job.depends_on_task)
		if not previous_attempt or previous_attempt.status != "Completed":
			frappe.throw(_("A chained Generation Task requires a completed upstream Attempt."))
		workflow = frappe.get_doc("Generation Workflow", job.workflow)
		if job.dependency_artifact_role:
			artifact = get_attempt_artifact(previous_attempt.name, job.dependency_artifact_role)
			if not artifact or not artifact.frappe_file:
				frappe.throw(
					_("The upstream Attempt has no usable {0} Artifact.").format(job.dependency_artifact_role)
				)
			staged["first_frame"] = [upload_frappe_file(artifact.frappe_file)["server_path"]]
			resolved_inputs["first_frame"] = [{
				"source": "Generation Artifact", "artifact": artifact.name,
				"artifact_role": job.dependency_artifact_role,
			}]
		else:
			last_frame_artifact = get_attempt_artifact(previous_attempt.name, "Last Frame")
			if not last_frame_artifact or not last_frame_artifact.frappe_file:
				frappe.throw(_("The upstream Attempt has no usable Last Frame Artifact."))
			staged["first_frame"] = [upload_frappe_file(last_frame_artifact.frappe_file)["server_path"]]
			resolved_inputs["first_frame"] = [{
				"source": "Generation Artifact",
				"artifact": last_frame_artifact.name,
			}]

	if not staged:
		required_file_inputs = [
			binding for binding in frappe.get_doc("Generation Workflow", job.workflow).bindings
			if binding.required and binding.required_input_role
		]
		if required_file_inputs:
			frappe.throw(_("Generation Task {0} has no resolved inputs.").format(job.name))

	attempt.resolved_inputs_json = json.dumps(resolved_inputs, sort_keys=True)
	attempt.save(ignore_permissions=True)
	return staged


def _reference_composition_roles(workflow):
	"""Read roles that should be composed into a deterministic image board."""
	try:
		spec = frappe.parse_json(getattr(workflow, "execution_spec", None) or "{}")
	except (TypeError, ValueError):
		spec = {}
	roles = ((spec.get("input_preprocessing") or {}).get("compose_image_roles") or [])
	if roles:
		return {frappe.scrub(role) for role in roles}
	return set()


def _reference_role_for_task_asset(job, asset_version):
	"""Resolve the role saved on the Shot Reference row for board guidance."""
	if not asset_version:
		return "general"
	from .reference_compositor import normalize_reference_role
	shot = frappe.get_doc("Shot", job.shot)
	for row in shot.get("generation_inputs") or []:
		if row.asset_version == asset_version:
			return normalize_reference_role(row.reference_role)
	return "general"


def _reference_label_for_task_asset(job, asset_version):
	if not asset_version:
		return ""
	project = frappe.db.get_value("Shot", job.shot, "media_project")
	if project:
		label = frappe.db.get_value(
			"Project Reference",
			{"parent": project, "parenttype": "Media Project", "asset_version": asset_version},
			"label",
		)
		if label:
			return label
	return frappe.db.get_value("Asset Version", asset_version, "file") or ""
