"""Candidate-only video generation from explicit motion/editing controls.

The deployment pins a workflow; clients supply semantic roles, never node names.
All media and direction are frozen in an ordinary Run/Task/Attempt. A candidate
cannot replace an approved take or trigger a whole-film export automatically.
"""

import hashlib
import json
import subprocess
from functools import wraps

import frappe

from joymedia.services.consistency.repair import _project_asset_path
from joymedia.services.consistency.tracking import file_hash
from joymedia.services.runtime.media import probe_video as _probe
from joymedia.services.workflows.capabilities import configured_workflow, require_controls
from joymedia.services.workflows.resolver import get_workflow_input_contract, validate_workflow_for_execution

ROLES = {"control_video", "control_mask", "identity_reference"}


def _validation_errors(function):
	@wraps(function)
	def wrapped(*args, **kwargs):
		try:
			return function(*args, **kwargs)
		except ValueError as exc:
			frappe.throw(str(exc))

	return wrapped


def _workflow():
	if frappe.conf.get("joymedia_guided_video_enabled", True) is not True:
		raise ValueError("Motion-guided repair is temporarily unavailable on this deployment.")
	name = configured_workflow("guided_video")
	if not name:
		raise ValueError("Motion-guided generation is not configured on this deployment.")
	workflow = frappe.get_doc("Generation Workflow", name)
	require_controls(workflow, {"control_video"})
	validate_workflow_for_execution(workflow)
	if workflow.output_media_type != "Video":
		raise ValueError("The motion-guided workflow must produce video.")
	return workflow


def _control_path(project, version):
	asset = frappe.get_doc("Asset Version", version)
	parent = frappe.get_doc("Media Asset", asset.media_asset)
	if (
		parent.asset_scope == "Library"
		and not parent.media_project
		and parent.owner == project.owner
		and parent.status == "Active"
	):
		path = frappe.get_doc("File", {"file_url": asset.file}).get_full_path()
		if file_hash(path) != asset.content_hash:
			raise ValueError("Control bytes no longer match their immutable version.")
		return path
	return _project_asset_path(project, version)


def validate_controls(project, workflow, inputs, frames):
	"""Validate role, access, immutable bytes and aligned time/space before admission."""
	if not isinstance(inputs, dict) or set(inputs) - ROLES:
		raise ValueError("Supply named motion-control assets.")
	contract = {item["role"]: item for item in get_workflow_input_contract(workflow)}
	if set(inputs) - set(contract):
		raise ValueError("The configured workflow does not accept these motion controls.")
	if not inputs.get("control_video"):
		raise ValueError("A motion guide video is required.")
	for role, binding in contract.items():
		if binding.get("min_count") and not inputs.get(role):
			raise ValueError(f"Missing required motion control: {role}")
	evidence = {}
	for role, version in inputs.items():
		if not isinstance(version, str) or not version:
			raise ValueError("Control assets must be existing version identifiers.")
		path = _control_path(project, version)
		asset = frappe.db.get_value("Asset Version", version, ["media_asset", "content_hash"], as_dict=True)
		media_type = frappe.db.get_value("Media Asset", asset.media_asset, "media_type")
		if media_type != ("Image" if role == "identity_reference" else "Video"):
			raise ValueError(f"Wrong media type for {role}.")
		metadata = {"asset_version": version, "sha256": asset.content_hash}
		if media_type == "Video":
			metadata.update(_probe(path))
			if metadata["frames"] < frames or abs(metadata["fps"] - float(workflow.output_fps)) > 0.001:
				raise ValueError("Guide and mask must cover the scene at the workflow frame rate.")
		else:
			from PIL import Image

			with Image.open(path) as image:
				image.verify()
		evidence[role] = metadata
	if "control_mask" in evidence:
		if any(
			evidence["control_mask"][key] != evidence["control_video"][key]
			for key in ("width", "height", "frames", "fps")
		):
			raise ValueError(
				"Editable-region mask and motion guide must align in dimensions, frames and frame rate."
			)
	return evidence


@frappe.whitelist()
@_validation_errors
def queue_guided_candidate(project_name, shot_name, expected_take, inputs, instruction=None):
	from joymedia.services.generation.runner import prepare_generation_task
	from joymedia.services.generation.takes import _ensure_scene_free, _project_shot
	from joymedia.services.planning.prompts import compile_prompt_for_documents
	from joymedia.services.planning.signature import assert_plan_matches_approval, compute_plan_signature
	from joymedia.services.project.context import build_project_snapshot

	project, shot = _project_shot(project_name, shot_name)
	if not expected_take or shot.selected_output_asset_version != expected_take:
		raise ValueError("The selected take changed. Reload before guiding another candidate.")
	if project.storyboard_approval_status != "Approved":
		raise ValueError("Approve the storyboard before guiding a video candidate.")
	assert_plan_matches_approval(project)
	direction = compute_plan_signature(project.name)
	workflow = _workflow()
	inputs = frappe.parse_json(inputs) if isinstance(inputs, str) else inputs
	frames = round(float(shot.duration_seconds) * float(workflow.output_fps))
	if not 1 <= frames <= int(workflow.frame_count):
		raise ValueError("The scene exceeds the guided workflow's capacity; split the interaction first.")
	evidence = validate_controls(project, workflow, inputs, frames)
	snapshot = json.loads(build_project_snapshot(project, require_production_pipeline=True)[0])
	row = next(row for row in snapshot["shots"] if row["shot"] == shot.name)
	row.update(
		workflow=workflow.name,
		generation_pipeline="",
		keyframe_task=None,
		keyframe_artifact=None,
		planned_frame_count=frames,
		references=[],
		graphic_overlays=[],
		closing_card=False,
		closing_hold_seconds=0,
	)
	snapshot.update(
		workflow=workflow.name,
		generation_pipeline="",
		output_fps=float(workflow.output_fps),
		shots=[row],
		guided_controls=evidence,
	)
	serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
	if instruction is not None and (
		not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2400
	):
		raise ValueError("Candidate direction must be nonempty text of at most 2400 characters.")
	prompt = (
		instruction.strip()
		if instruction
		else compile_prompt_for_documents(shot, project, prompt_source="motion")
	)
	if instruction:
		row["generation_prompt"] = prompt
		serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
	# Serialise admission only, while uploads and inference remain background work.
	frappe.db.commit()
	with frappe.cache.lock(
		f"joymedia-take-admission:{frappe.local.site}:{project.name}", timeout=600, blocking_timeout=120
	):
		frappe.db.commit()
		_ensure_scene_free(project, shot)
		project.reload()
		if (
			project.storyboard_approval_status != "Approved"
			or compute_plan_signature(project.name) != direction
		):
			raise ValueError("The direction changed during motion-control admission.")
		shot.reload()
		if shot.selected_output_asset_version != expected_take:
			raise ValueError("The selected take changed during motion-control admission.")
		run = frappe.get_doc(
			dict(
				doctype="Generation Run",
				media_project=project.name,
				workflow=workflow.name,
				project_snapshot_json=serialized,
				project_snapshot_hash=hashlib.sha256(serialized.encode()).hexdigest(),
				execution_scope_json=json.dumps(
					{
						"shot_names": [shot.name],
						"candidate_only": True,
						"expected_take": expected_take,
						"plan_signature": direction,
					}
				),
				requested_by=frappe.session.user,
				status="Queued",
			)
		).insert(ignore_permissions=True)
		task = frappe.get_doc(
			dict(
				doctype="Generation Task",
				generation_run=run.name,
				shot=shot.name,
				workflow=workflow.name,
				prompt_text=prompt,
				prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
				segment_index=1,
				segment_frame_count=frames,
				segment_effective_frames=frames,
				segment_start_frame=0,
				overlap_frames=0,
				status="Draft",
			)
		).insert(ignore_permissions=True)
		prepare_generation_task(
			task.name,
			[{"reference_role": role, "asset_version": version} for role, version in inputs.items()],
		)
		frappe.enqueue(
			"joymedia.services.generation.orchestrator.submit_run",
			queue="long",
			timeout=1800,
			enqueue_after_commit=True,
			run_name=run.name,
		)
		frappe.db.commit()
	return {"run": run.name, "task": task.name, "status": "Queued"}


@frappe.whitelist()
@_validation_errors
def guided_candidate_status(project_name, run_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	run = frappe.get_doc("Generation Run", run_name)
	if run.media_project != project.name:
		frappe.throw("Candidate does not belong to this project.", frappe.PermissionError)
	scope = json.loads(run.execution_scope_json or "{}")
	if not scope.get("candidate_only"):
		raise ValueError("This run is not a guided candidate.")
	result = {"run": run.name, "status": run.status, "error": run.error_summary, "video": None}
	if run.status == "Completed":
		task = frappe.db.get_value("Generation Task", {"generation_run": run.name}, "name")
		attempt = frappe.db.get_value(
			"Generation Attempt", {"generation_task": task, "status": "Completed"}, "name"
		)
		url = frappe.db.get_value(
			"Generation Artifact",
			{"generation_attempt": attempt, "artifact_role": "Primary Video"},
			"frappe_file",
		)
		if url:
			from joymedia.services.keyframes.stage import attach_keyframe_to_project

			attach_keyframe_to_project(url, project.name)
			result["video"] = url
			asset = frappe.db.get_value(
				"Media Asset",
				{"asset_name": f"{scope['shot_names'][0]} Output", "media_project": project.name},
				"name",
			)
			result["asset_version"] = frappe.db.get_value(
				"Asset Version",
				{"media_asset": asset, "source_generation_attempt": attempt, "source": "Composed"},
				"name",
				order_by="creation asc",
			)
	return result


@frappe.whitelist()
@_validation_errors
def use_guided_candidate(project_name, run_name, expected_take):
	"""Explicitly select a completed candidate; brand/release approval stays separate."""
	from joymedia.services.generation.takes import _project_shot, scene_takes, select_scene_take
	from joymedia.services.planning.signature import compute_plan_signature

	state = guided_candidate_status(project_name, run_name)
	run = frappe.get_doc("Generation Run", run_name)
	scope = json.loads(run.execution_scope_json)
	project, shot = _project_shot(project_name, scope["shot_names"][0])
	if state["status"] != "Completed" or not state.get("asset_version"):
		raise ValueError("The guided candidate is not ready.")
	frappe.db.sql("select name from `tabShot` where name=%s for update", shot.name)
	shot.reload()
	if expected_take != scope["expected_take"] or shot.selected_output_asset_version != expected_take:
		raise ValueError("The selected take changed; review the candidate against the current take.")
	if scope.get("plan_signature") and scope["plan_signature"] != compute_plan_signature(project.name):
		raise ValueError("The scene direction changed since this candidate was requested.")
	names = [row.name for row in scene_takes(project.name, shot.name)]
	return select_scene_take(project.name, shot.name, names.index(state["asset_version"]) + 1)
