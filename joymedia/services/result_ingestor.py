from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile

import frappe
from frappe import _
from frappe.utils.synchronization import filelock
from frappe.utils import convert_utc_to_system_timezone, get_datetime, now, time_diff_in_seconds

from .comfyui_client import download_output, get_history, get_queue_state, probe_output
from .artifact_service import get_attempt_artifact
from joymedia.workflow_adapters import get_workflow_adapter

# ComfyUI may not list a just-submitted prompt in /queue or /history yet.
MISSING_JOB_GRACE_SECONDS = 15


class UnusableComfyUIOutput(frappe.ValidationError):
	"""ComfyUI finished, but its output cannot be ingested; retrying the sync will not help."""


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
	with filelock(f"joymedia-sync-attempt-{attempt_name}"):
		return _sync_attempt_result(attempt_name)


def _sync_attempt_result(attempt_name):
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	primary = get_attempt_artifact(attempt.name, "Primary Video")
	if attempt.status == "Completed" and primary:
		artifact = primary
		_store_artifact_file_in_frappe(artifact, attempt)
		_refresh_parent_execution_state(attempt.name)
		return {
			"status": attempt.status,
			"output_artifact": artifact.name,
		}
	if not attempt.external_job_id:
		frappe.throw(_("Generation Attempt {0} has no ComfyUI prompt ID.").format(attempt.name))

	history = get_history(attempt.external_job_id, base_url=attempt.comfyui_endpoint_url)
	history = history.get(attempt.external_job_id, history)
	if not history:
		return _sync_attempt_without_history(attempt)

	status = history.get("status", {})
	status_string = status.get("status_str")

	if status_string in ("error", "failed"):
		messages = status.get("messages") or []
		return _fail_attempt(attempt, _("ComfyUI execution failed."), str(messages), "Generation")

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

	workflow_name = (
		frappe.db.get_value("Generation Task", attempt.generation_task, "workflow")
		if getattr(attempt, "generation_task", None)
		else None
	)
	workflow = frappe.get_doc("Generation Workflow", workflow_name) if workflow_name else None
	preferred_nodes = None
	if workflow:
		adapter = get_workflow_adapter(workflow)
		preferred_nodes = getattr(adapter, "primary_output_node_keys", None) or None
	output = _find_primary_mp4(history, preferred_node_keys=preferred_nodes)
	if not output:
		_log_sync_failure(attempt, "returned no MP4 output: %s", history.get("outputs"))
		return _fail_attempt(
			attempt, _("ComfyUI completed but returned no usable MP4 output."), None, "Generation"
		)

	try:
		artifact, last_frame_artifact = _ingest_completed_output(attempt, history, output)
	except UnusableComfyUIOutput as exc:
		return _fail_attempt(
			attempt, _("ComfyUI completed but its output could not be processed."), str(exc), "Generation"
		)
	return _complete_attempt(attempt, history, artifact, last_frame_artifact)


def _sync_attempt_without_history(attempt):
	"""Resolve an Attempt whose prompt has no ComfyUI history entry yet."""
	queue_state = get_queue_state(attempt.external_job_id, base_url=attempt.comfyui_endpoint_url)
	if queue_state == "running":
		attempt.status = "Running"
		if not attempt.started_at:
			attempt.started_at = now()
	elif queue_state == "pending" or _within_missing_job_grace_period(attempt):
		attempt.status = "Queued"
	else:
		job = frappe.get_doc("Generation Task", attempt.generation_task) if attempt.get("generation_task") else None
		output_filename = f"{job.name}_{attempt.name}_00001_.mp4" if job else None
		if output_filename and probe_output(output_filename, base_url=attempt.comfyui_endpoint_url):
			history = {
				"status": {"completed": True},
				"outputs": {"joymedia_probe": {"images": [{"filename": output_filename, "type": "output"}]}},
			}
			try:
				artifact, last_frame_artifact = _ingest_completed_output(attempt, history, history["outputs"]["joymedia_probe"]["images"][0])
			except UnusableComfyUIOutput as exc:
				return _fail_attempt(attempt, "ComfyUI output could not be processed.", str(exc), "Generation")
			return _complete_attempt(attempt, history, artifact, last_frame_artifact)
		_log_sync_failure(attempt, "is missing from ComfyUI /history and /queue")
		return _fail_attempt(
			attempt,
			_("ComfyUI job is no longer present in the queue or execution history."),
			None,
			"Infrastructure",
		)
	attempt.save(ignore_permissions=True)
	_refresh_parent_execution_state(attempt.name)
	return {"status": attempt.status}


def _within_missing_job_grace_period(attempt):
	if not attempt.queued_at:
		return False
	return time_diff_in_seconds(now(), attempt.queued_at) < MISSING_JOB_GRACE_SECONDS


def _log_sync_failure(attempt, message, *args):
	frappe.logger("joymedia.result_sync").warning(
		"Generation Attempt %s (prompt %s) " + message, attempt.name, attempt.external_job_id, *args
	)


def _fail_attempt(attempt, error_summary, error_details, failure_class):
	from .user_messages import friendly_failure, technical_message
	attempt.status = "Failed"
	attempt.error_summary = friendly_failure(failure_class, error_summary)
	attempt.error_details = technical_message(error_details or error_summary)
	attempt.failure_class = failure_class
	attempt.save(ignore_permissions=True)
	for dependent in frappe.get_all(
		"Generation Task",
		filters={
			"depends_on_task": attempt.generation_task,
			"status": ["not in", ["Completed", "Failed", "Cancelled"]],
		},
		pluck="name",
	):
		frappe.db.set_value(
			"Generation Task",
			dependent,
			{
				"status": "Cancelled",
				"failure_class": "Cancelled",
				"error_summary": "Skipped because the previous scene segment failed.",
			},
			update_modified=False,
		)
	_refresh_parent_execution_state(attempt.name)
	return {"status": attempt.status}


def _ingest_completed_output(attempt, history, output):
	workflow_name = frappe.db.get_value("Generation Task", attempt.generation_task, "workflow")
	workflow = frappe.get_doc("Generation Workflow", workflow_name) if workflow_name else None
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
	continuation_state = _find_continuation_state(history)
	if workflow and get_workflow_adapter(workflow).cumulative_segment_output:
		dependants = frappe.db.exists(
			"Generation Task",
			{"depends_on_task": attempt.generation_task, "status": ["not in", ["Completed", "Failed", "Cancelled"]]},
		)
		if dependants and not continuation_state:
			raise UnusableComfyUIOutput("Cumulative output did not include continuation state.")
	if continuation_state:
		_store_continuation_state(attempt, continuation_state)
	return artifact, get_attempt_artifact(attempt.name, "Last Frame")


def _complete_attempt(attempt, history, artifact, last_frame_artifact):
	attempt.status = "Completed"
	if not attempt.started_at:
		attempt.started_at = _execution_timestamp(history, "execution_start") or now()
	attempt.completed_at = now()
	if attempt.started_at:
		attempt.runtime_seconds = max(
			0, (get_datetime(attempt.completed_at) - get_datetime(attempt.started_at)).total_seconds()
		)
	attempt.save(ignore_permissions=True)
	_refresh_parent_execution_state(attempt.name)
	return {
		"status": attempt.status,
		"output_artifact": artifact.name,
		"last_frame_artifact": last_frame_artifact.name if last_frame_artifact else None,
	}

def _find_last_frame_image(history):
	node_output = (history.get("outputs") or {}).get("save_last_frame", {})
	for output in node_output.get("images", []):
		filename = str(output.get("filename", "")).lower()
		if filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
			return output
	return None


def _store_last_frame(attempt, output):
	last_frame_artifact = get_attempt_artifact(attempt.name, "Last Frame")
	if last_frame_artifact:
		return last_frame_artifact

	image_bytes = download_output(
		output["filename"],
		output.get("subfolder", ""),
		output.get("type", "output"),
		base_url=attempt.comfyui_endpoint_url,
	)
	return _store_last_frame_bytes(attempt, image_bytes, Path(output["filename"]).name)


def _store_last_frame_bytes(attempt, image_bytes, file_name):
	last_frame_artifact = get_attempt_artifact(attempt.name, "Last Frame")
	if last_frame_artifact:
		return last_frame_artifact

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": image_bytes,
			"is_private": 1,
		}
	)
	file_doc.insert(ignore_permissions=True)
	artifact = frappe.get_doc(
		{
			"doctype": "Generation Artifact",
			"artifact_key": f"{attempt.name}:last_frame",
			"artifact_role": "Last Frame",
			"generation_attempt": attempt.name,
			"media_type": "Image",
		}
	)
	artifact.insert(ignore_permissions=True)
	file_doc.attached_to_doctype = "Generation Artifact"
	file_doc.attached_to_name = artifact.name
	file_doc.save(ignore_permissions=True)
	artifact.frappe_file = file_doc.file_url
	artifact.save(ignore_permissions=True)
	return artifact


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
		frappe.throw(
			_("Unable to extract the last frame from ComfyUI output: {0}").format(exc),
			exc=UnusableComfyUIOutput,
		)


def _create_primary_artifact(attempt):
	artifact_key = f"{attempt.name}:primary_video"
	existing = get_attempt_artifact(attempt.name, "Primary Video")
	if existing:
		return existing

	artifact = frappe.get_doc(
		{
			"doctype": "Generation Artifact",
			"artifact_key": artifact_key,
			"artifact_role": "Primary Video",
			"generation_attempt": attempt.name,
			"media_type": "Video",
		}
	)
	artifact.insert(ignore_permissions=True)
	return artifact


def _store_artifact_file_in_frappe(artifact, attempt, output=None):
	"""Persist a raw ComfyUI output as a Generation Artifact file."""
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


def _refresh_parent_execution_state(attempt_name):
	from .generation_orchestrator import refresh_generation_state_for_attempt

	refresh_generation_state_for_attempt(attempt_name)


def _execution_timestamp(history, message_name):
	for name, details in history.get("status", {}).get("messages", []):
		if name == message_name and details.get("timestamp"):
			# Frappe stores naive datetimes in the system time zone, not UTC.
			utc = datetime.fromtimestamp(details["timestamp"] / 1000, tz=timezone.utc)
			return convert_utc_to_system_timezone(utc).replace(tzinfo=None)
	return None


def _find_primary_mp4(history, preferred_node_keys=None):
	outputs = history.get("outputs") or {}
	ordered_keys = []
	if preferred_node_keys:
		ordered_keys.extend(key for key in preferred_node_keys if key in outputs)
	ordered_keys.extend(key for key in outputs if key not in ordered_keys)
	for node_key in ordered_keys:
		node_outputs = outputs[node_key]
		for output in (
			node_outputs.get("gifs", [])
			+ node_outputs.get("videos", [])
			+ node_outputs.get("images", [])
		):
			if str(output.get("filename", "")).lower().endswith(".mp4"):
				return output
	return None


def _find_continuation_state(history):
	"""Find the basename emitted by a Sato latent-save node."""
	for node_outputs in (history.get("outputs") or {}).values():
		if not isinstance(node_outputs, dict):
			continue
		for value in node_outputs.get("text") or []:
			filename = value.get("filename") if isinstance(value, dict) else value
			if not filename:
				continue
			filename = Path(str(filename)).name
			if filename.lower().endswith((".h3latent", ".h3latent.safetensors")):
				return filename
		for values in node_outputs.values():
			if not isinstance(values, list):
				continue
			for output in values:
				filename = output.get("filename") if isinstance(output, dict) else output
				if not filename:
					continue
				filename = Path(str(filename)).name
				if filename.lower().endswith((".h3latent", ".h3latent.safetensors")):
					return filename
	return None


def _store_continuation_state(attempt, provider_locator):
	artifact = get_attempt_artifact(attempt.name, "Continuation State")
	if artifact:
		return artifact
	return frappe.get_doc(
		{
			"doctype": "Generation Artifact",
			"artifact_key": f"{attempt.name}:continuation_state",
			"artifact_role": "Continuation State",
			"generation_attempt": attempt.name,
			"media_type": "Other",
			"provider_locator": provider_locator,
		}
	).insert(ignore_permissions=True)
