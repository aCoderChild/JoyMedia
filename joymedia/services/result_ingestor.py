from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile

import frappe
from frappe import _
from frappe.utils import get_datetime, now

from .comfyui_client import download_output, get_history


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

	history = get_history(attempt.external_job_id, base_url=attempt.comfyui_endpoint_url)
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

	artifact = _create_primary_artifact(attempt)
	_store_artifact_file_in_frappe(artifact, attempt, output)
	last_frame = _find_last_frame_image(history)
	if last_frame:
		_store_last_frame(attempt, last_frame)
	else:
		video_bytes = download_output(
			output["filename"],
			output.get("subfolder", ""),
			output.get("type", "output"),
			base_url=attempt.comfyui_endpoint_url,
		)
		_store_last_frame_bytes(
			attempt,
			_extract_last_frame(video_bytes, output["filename"]),
			f"{Path(output['filename']).stem}_last_frame.png",
		)
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
	if _should_auto_select_output(attempt):
		_auto_select_output(attempt, artifact)
	else:
		_create_pending_quality_review(attempt, artifact)
	_refresh_parent_execution_state(attempt.name)
	return {
		"status": attempt.status,
		"output_artifact": artifact.name,
		"last_frame_asset_version": attempt.last_frame_asset_version,
	}


def _should_auto_select_output(attempt):
	job = frappe.get_doc("Generation Job", attempt.generation_job)
	if not job.generation_run:
		return False
	return bool(frappe.db.get_value("Generation Run", job.generation_run, "auto_compose"))


def _auto_select_output(attempt, artifact):
	from joymedia.services.artifact_service import promote_artifact

	job = frappe.get_doc("Generation Job", attempt.generation_job)
	shot = frappe.get_doc("Shot Specification", job.shot_specification)
	result = promote_artifact(artifact.name, require_approved_review=False)
	shot.db_set("selected_output_asset_version", result["asset_version"], update_modified=False)


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

	image_bytes = download_output(
		output["filename"],
		output.get("subfolder", ""),
		output.get("type", "output"),
		base_url=attempt.comfyui_endpoint_url,
	)
	return _store_last_frame_bytes(attempt, image_bytes, Path(output["filename"]).name)


def _store_last_frame_bytes(attempt, image_bytes, file_name):
	if attempt.last_frame_asset_version:
		return frappe.get_doc("Asset Version", attempt.last_frame_asset_version)

	job = frappe.get_doc("Generation Job", attempt.generation_job)
	shot = frappe.get_doc("Shot Specification", job.shot_specification)
	media_specification = frappe.get_doc("Media Specification", shot.media_specification)
	media_asset = _get_or_create_continuation_asset(shot.name, media_specification.media_project)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
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


def _extract_last_frame(video_bytes, source_name):
	"""Extract a continuation frame when the workflow only returns a video."""
	try:
		with tempfile.TemporaryDirectory(prefix="joymedia-last-frame-") as temp_dir:
			video_path = Path(temp_dir) / Path(source_name).name
			frame_path = Path(temp_dir) / "last_frame.png"
			video_path.write_bytes(video_bytes)
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-sseof",
					"-0.1",
					"-i",
					str(video_path),
					"-frames:v",
					"1",
					str(frame_path),
				],
				check=True,
				capture_output=True,
			)
			return frame_path.read_bytes()
	except (OSError, subprocess.CalledProcessError) as exc:
		frappe.throw(_("Unable to extract the last frame from ComfyUI output: {0}").format(exc))


def _get_or_create_continuation_asset(shot_name, media_project):
	asset_name = f"{shot_name} Continuation Frames"
	media_asset_name = frappe.db.get_value("Media Asset", {"asset_name": asset_name}, "name")
	if media_asset_name:
		return frappe.get_doc("Media Asset", media_asset_name)

	media_asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": asset_name,
			"media_type": "Image",
			"asset_category": "Other",
			"library_visibility": "Internal",
			"media_project": media_project,
			"client_organization": frappe.db.get_value("Media Project", media_project, "client_organization"),
		}
	)
	media_asset.insert(ignore_permissions=True)
	return media_asset


def _create_primary_artifact(attempt):
	artifact_key = f"{attempt.name}:primary_video"
	existing = frappe.db.get_value("Generation Artifact", {"artifact_key": artifact_key}, "name")
	if existing:
		return frappe.get_doc("Generation Artifact", existing)

	artifact = frappe.get_doc(
		{
			"doctype": "Generation Artifact",
			"artifact_key": artifact_key,
			"generation_attempt": attempt.name,
			"media_type": "Video",
			"lifecycle_status": "Temporary",
		}
	)
	artifact.insert(ignore_permissions=True)
	return artifact


def _store_artifact_file_in_frappe(artifact, attempt, output=None):
	"""Copy a temporary ComfyUI output into Frappe for review without promoting it."""
	if artifact.frappe_file:
		return artifact

	if output is None:
		history = get_history(attempt.external_job_id, base_url=attempt.comfyui_endpoint_url)
		history = history.get(attempt.external_job_id, history)
		output = _find_primary_mp4(history)
	if not output:
		frappe.throw(_("Generation Artifact {0} has no available video output.").format(artifact.name))

	video_bytes = download_output(
		output["filename"],
		output.get("subfolder", ""),
		output.get("type", "output"),
		base_url=attempt.comfyui_endpoint_url,
	)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": Path(output["filename"]).name,
			"content": video_bytes,
			"is_private": 1,
			"attached_to_doctype": "Generation Artifact",
			"attached_to_name": artifact.name,
		}
	)
	file_doc.insert(ignore_permissions=True)
	artifact.frappe_file = file_doc.file_url
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
