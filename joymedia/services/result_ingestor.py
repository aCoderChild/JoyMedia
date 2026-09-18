from datetime import datetime, timezone
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now, now_datetime

from .comfyui_client import download_output, get_history
from .execution_router import get_worker


def sync_active_attempts():
	"""Poll active ComfyUI attempts and ingest any completed outputs."""
	results = []
	for attempt in frappe.get_all(
		"Generation Attempt",
		filters={"status": ["in", ["Queued", "Running"]]},
		fields=["name", "external_job_id"],
	):
		if not attempt.external_job_id:
			continue

		try:
			result = sync_attempt_result(attempt.name)
			frappe.db.commit()
			results.append({"attempt": attempt.name, **result})
		except Exception:
			frappe.db.rollback()
			frappe.logger("joymedia.result_sync").exception(
				"Unable to synchronize Generation Attempt %s", attempt.name
			)
	return results


def sync_attempt_result(attempt_name):
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	if attempt.status == "Completed" and attempt.output_artifact:
		artifact = frappe.get_doc("Generation Artifact", attempt.output_artifact)
		_store_artifact_file_in_frappe(artifact, attempt)
		_refresh_parent_execution_state(attempt.name)
		return {
			"status": attempt.status,
			"output_artifact": attempt.output_artifact,
		}
	if attempt.status == "Completed" and attempt.output_asset_version:
		_refresh_parent_execution_state(attempt.name)
		return {"status": attempt.status, "output_asset_version": attempt.output_asset_version}
	if not attempt.external_job_id:
		frappe.throw(_("Generation Attempt {0} has no ComfyUI prompt ID.").format(attempt.name))

	worker = get_worker(attempt.comfyui_worker)
	base_url = attempt.comfyui_endpoint_url or (worker.endpoint_url if worker else None)
	history = get_history(attempt.external_job_id, base_url=base_url)
	history = history.get(attempt.external_job_id, history)
	status = history.get("status", {})
	status_string = status.get("status_str")

	if status_string in ("error", "failed"):
		messages = status.get("messages") or []
		attempt.status = "Failed"
		attempt.error_summary = _("ComfyUI execution failed.")
		attempt.error_details = str(messages)
		attempt.save(ignore_permissions=True)
		_refresh_parent_execution_state(attempt.name)
		return {"status": attempt.status}

	if not status.get("completed"):
		if status_string == "executing":
			attempt.status = "Running"
			if not attempt.started_at:
				attempt.started_at = now()
		else:
			attempt.status = "Queued"
		attempt.save(ignore_permissions=True)
		_refresh_parent_execution_state(attempt.name)
		return {"status": attempt.status}

	output = _find_primary_mp4(history)
	if not output:
		frappe.throw(_("ComfyUI completed without a primary MP4 output."))

	artifact = _create_primary_artifact(attempt, output)
	_store_artifact_file_in_frappe(artifact, attempt)
	last_frame = _find_last_frame_image(history)
	if not last_frame:
		frappe.throw(_("ComfyUI completed without a last-frame image output."))
	_store_last_frame(attempt, last_frame)
	attempt.output_artifact = artifact.name
	attempt.status = "Completed"
	if not attempt.started_at:
		attempt.started_at = _execution_timestamp(history, "execution_start") or now()
	attempt.completed_at = now()
	if attempt.started_at:
		attempt.runtime_seconds = max(
			0, (get_datetime(attempt.completed_at) - get_datetime(attempt.started_at)).total_seconds()
		)
	attempt.save(ignore_permissions=True)
	_create_pending_quality_review(attempt, artifact)
	_refresh_parent_execution_state(attempt.name)
	return {
		"status": attempt.status,
		"output_artifact": artifact.name,
		"last_frame_asset_version": attempt.last_frame_asset_version,
	}


def _find_last_frame_image(history):
	node_output = (history.get("outputs") or {}).get("save_last_frame", {})
	for output in node_output.get("images", []):
		filename = str(output.get("filename", "")).lower()
		if filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
			return output
	return None


def _store_last_frame(attempt, output):
	if attempt.last_frame_asset_version:
		return frappe.get_doc("Asset Version", attempt.last_frame_asset_version)

	job = frappe.get_doc("Generation Job", attempt.generation_job)
	shot = frappe.get_doc("Shot Specification", job.shot_specification)
	media_specification = frappe.get_doc("Media Specification", shot.media_specification)
	media_asset = _get_or_create_continuation_asset(shot.name, media_specification.media_project)

	image_bytes = download_output(
		output["filename"],
		output.get("subfolder", ""),
		output.get("type", "output"),
		base_url=attempt.comfyui_endpoint_url,
	)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": Path(output["filename"]).name,
			"content": image_bytes,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": media_asset.name,
		}
	)
	file_doc.insert(ignore_permissions=True)

	asset_version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": media_asset.name,
			"file": file_doc.file_url,
			"source": "Generated",
		}
	)
	asset_version.insert(ignore_permissions=True)
	attempt.last_frame_asset_version = asset_version.name
	return asset_version


def _get_or_create_continuation_asset(shot_name, media_project):
	asset_name = f"{shot_name} Continuation Frames"
	media_asset_name = frappe.db.get_value("Media Asset", {"asset_name": asset_name}, "name")
	if media_asset_name:
		return frappe.get_doc("Media Asset", media_asset_name)

	media_asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": asset_name,
			"asset_scope": "Project",
			"media_type": "Image",
			"asset_category": "Reference",
			"media_project": media_project,
		}
	)
	media_asset.insert(ignore_permissions=True)
	return media_asset


def _create_primary_artifact(attempt, output):
	artifact_key = f"{attempt.name}:primary_video"
	existing = frappe.db.get_value("Generation Artifact", {"artifact_key": artifact_key}, "name")
	if existing:
		return frappe.get_doc("Generation Artifact", existing)

	artifact = frappe.get_doc(
		{
			"doctype": "Generation Artifact",
			"artifact_key": artifact_key,
			"generation_attempt": attempt.name,
			"artifact_role": "Primary Video",
			"media_type": "Video",
			"storage_backend": "ComfyUI",
			"remote_filename": output["filename"],
			"remote_subfolder": output.get("subfolder", ""),
			"remote_file_type": output.get("type", "output"),
			"lifecycle_status": "Temporary",
			"expires_at": add_to_date(now_datetime(), hours=72),
		}
	)
	artifact.insert(ignore_permissions=True)
	return artifact


def _store_artifact_file_in_frappe(artifact, attempt):
	"""Copy a temporary ComfyUI output into Frappe for review without promoting it."""
	if artifact.frappe_file:
		return artifact
	if not artifact.remote_filename:
		frappe.throw(_("Generation Artifact {0} has no remote filename.").format(artifact.name))

	video_bytes = download_output(
		artifact.remote_filename,
		artifact.remote_subfolder or "",
		artifact.remote_file_type or "output",
		base_url=attempt.comfyui_endpoint_url,
	)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": Path(artifact.remote_filename).name,
			"content": video_bytes,
			"is_private": 1,
			"attached_to_doctype": "Generation Artifact",
			"attached_to_name": artifact.name,
		}
	)
	file_doc.insert(ignore_permissions=True)
	artifact.storage_backend = "Frappe File"
	artifact.frappe_file = file_doc.file_url
	artifact.storage_uri = file_doc.file_url
	artifact.mime_type = "video/mp4"
	artifact.size_bytes = len(video_bytes)
	artifact.save(ignore_permissions=True)
	return artifact


def _create_pending_quality_review(attempt, artifact):
	if frappe.db.exists(
		"Quality Review",
		{"generation_artifact": artifact.name},
	):
		return

	frappe.get_doc(
		{
			"doctype": "Quality Review",
			"generation_artifact": artifact.name,
			"status": "Pending",
		}
	).insert(ignore_permissions=True)


def _refresh_parent_execution_state(attempt_name):
	from .generation_orchestrator import refresh_generation_state_for_attempt

	refresh_generation_state_for_attempt(attempt_name)


def _execution_timestamp(history, message_name):
	for name, details in history.get("status", {}).get("messages", []):
		if name == message_name and details.get("timestamp"):
			return datetime.fromtimestamp(details["timestamp"] / 1000, tz=timezone.utc).replace(
				tzinfo=None
			)
	return None


def _find_primary_mp4(history):
	for node_outputs in (history.get("outputs") or {}).values():
		for output in node_outputs.get("gifs", []) + node_outputs.get("videos", []):
			if str(output.get("filename", "")).lower().endswith(".mp4"):
				return output
	return None
