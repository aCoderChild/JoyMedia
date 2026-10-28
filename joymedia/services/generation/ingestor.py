"""Collects what ComfyUI produced: downloads the output into a Generation Artifact, extracts the last frame, and
moves the attempt to Completed or Failed. Also the cron that syncs every active attempt.
"""

import subprocess
import tempfile
import time
from datetime import UTC, datetime, timezone
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import convert_utc_to_system_timezone, get_datetime, now, time_diff_in_seconds
from frappe.utils.synchronization import filelock

from joymedia.services.generation.artifacts import get_attempt_artifact
from joymedia.services.generation.timing import record as record_timing
from joymedia.services.generation.timing import record_comfy_execution
from joymedia.services.workflows.comfyui import download_output, get_history, get_queue_state, probe_output

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


def _sync_attempt_result(attempt_name, *, history=None):
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	workflow = _attempt_workflow(attempt)
	primary = get_attempt_artifact(
		attempt.name, workflow.primary_artifact_role if workflow else "Primary Video"
	)
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

	if history is None:
		history = get_history(attempt.external_job_id, base_url=attempt.comfyui_endpoint_url)
	history = history.get(attempt.external_job_id, history)
	if not history:
		return _sync_attempt_without_history(attempt)

	status = history.get("status", {})
	status_string = status.get("status_str")
	record_comfy_execution(attempt, history)

	if status_string in ("error", "failed"):
		messages = status.get("messages") or []
		return _fail_attempt(
			attempt, _("ComfyUI execution failed."), str(messages), "Generation", history=history
		)

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

	workflow = _attempt_workflow(attempt)
	preferred_nodes = (
		[str(workflow.primary_output_node_key)] if workflow and workflow.primary_output_node_key else None
	)
	output = _find_primary_output(history, workflow, preferred_node_keys=preferred_nodes)
	if not output:
		output_label = "MP4" if not workflow or workflow.output_media_type == "Video" else "primary output"
		_log_sync_failure(attempt, "returned no usable %s: %s", output_label, history.get("outputs"))
		return _fail_attempt(
			attempt,
			_("ComfyUI completed but returned no usable {0}.").format(output_label),
			None,
			"Generation",
			history=history,
		)

	from joymedia.services.consistency.retention import RetentionRejected

	ingest_start = time.monotonic()
	try:
		artifact, last_frame_artifact = _ingest_completed_output(attempt, history, output)
	except RetentionRejected as exc:
		record_timing(attempt, "output_ingestion_seconds", time.monotonic() - ingest_start)
		return _fail_attempt(
			attempt,
			"The product reference needs attention before this scene can be used.",
			str(exc),
			"Input",
			history=history,
		)
	except ValueError as exc:
		record_timing(attempt, "output_ingestion_seconds", time.monotonic() - ingest_start)
		return _fail_attempt(attempt, "Visual admission rejected", str(exc), "Input", history=history)
	except UnusableComfyUIOutput as exc:
		record_timing(attempt, "output_ingestion_seconds", time.monotonic() - ingest_start)
		return _fail_attempt(
			attempt,
			_("ComfyUI completed but its output could not be processed."),
			str(exc),
			"Generation",
			history=history,
		)
	record_timing(attempt, "output_ingestion_seconds", time.monotonic() - ingest_start)
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
		# Completion can occur between the first /history read and /queue.
		# Absence from that later queue is not evidence that the prompt was lost.
		latest = get_history(attempt.external_job_id, base_url=attempt.comfyui_endpoint_url)
		latest = latest.get(attempt.external_job_id, latest)
		if latest:
			return _sync_attempt_result(attempt.name, history=latest)
		job = (
			frappe.get_doc("Generation Task", attempt.generation_task)
			if attempt.get("generation_task")
			else None
		)
		output_filename = f"{job.name}_{attempt.name}_00001_.mp4" if job else None
		if output_filename and probe_output(output_filename, base_url=attempt.comfyui_endpoint_url):
			history = {
				"status": {"completed": True},
				"outputs": {"joymedia_probe": {"images": [{"filename": output_filename, "type": "output"}]}},
			}
			try:
				artifact, last_frame_artifact = _ingest_completed_output(
					attempt, history, history["outputs"]["joymedia_probe"]["images"][0]
				)
			except UnusableComfyUIOutput as exc:
				return _fail_attempt(
					attempt, "ComfyUI output could not be processed.", str(exc), "Generation"
				)
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


# Why a dependent task was cancelled when its predecessor failed; retrying the predecessor revives exactly these.
CASCADE_CANCEL_SUMMARY = "Skipped because the previous scene segment failed."


def _will_retry_automatically(attempt):
	"""Mirror the orchestrator's automatic retry rule for a just-failed attempt."""
	from joymedia.services.generation.orchestrator import MAX_AUTOMATIC_RETRIES

	if attempt.failure_class in {"Workflow", "Input"}:
		return False
	retries = frappe.db.count(
		"Generation Attempt", {"generation_task": attempt.generation_task, "retry_of": ["is", "set"]}
	)
	return retries < MAX_AUTOMATIC_RETRIES


def _fail_attempt(attempt, error_summary, error_details, failure_class, *, history=None):
	from joymedia.services.generation.failures import classify_failure, friendly_failure, technical_message

	# ComfyUI often reports an authentication or node setup error as a generic
	# execution failure. Preserve the actionable cause for orchestration and the
	# studio instead of retrying it as if the GPU were merely busy.
	detected_failure_class = classify_failure(error_details or error_summary, failure_class)
	# Preserve the caller's known execution category for ordinary ComfyUI output
	# failures; only promote configuration/input problems that require a human
	# change before another submission can succeed.
	if detected_failure_class in {"Workflow", "Input"} and failure_class != "Input":
		failure_class = detected_failure_class
	attempt.status = "Failed"
	attempt.error_summary = friendly_failure(failure_class, error_details or error_summary)
	attempt.error_details = technical_message(error_details or error_summary)
	attempt.failure_class = failure_class
	started_at = attempt.get("started_at")
	if not isinstance(started_at, (str, datetime)):
		started_at = None
	if not started_at and history:
		started_at = _execution_timestamp(history, "execution_start")
		attempt.started_at = started_at
	attempt.completed_at = now()
	if started_at:
		attempt.runtime_seconds = max(
			0, (get_datetime(attempt.completed_at) - get_datetime(started_at)).total_seconds()
		)
	attempt.save(ignore_permissions=True)
	if _will_retry_automatically(attempt):
		# Dependents wait for the retry; cancelling them now would strand the chain
		# even when the retry succeeds.
		_refresh_parent_execution_state(attempt.name)
		return {"status": attempt.status}
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
				"error_summary": CASCADE_CANCEL_SUMMARY,
			},
			update_modified=False,
		)
	_refresh_parent_execution_state(attempt.name)
	return {"status": attempt.status}


def _ingest_completed_output(attempt, history, output):
	workflow = _attempt_workflow(attempt)
	artifact = _create_primary_artifact(attempt, workflow)
	_store_artifact_file_in_frappe(artifact, attempt, output)
	if not workflow or workflow.output_media_type != "Video":
		return artifact, None
	last_frame = _find_last_frame_image(history, workflow)
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
	return artifact, get_attempt_artifact(attempt.name, "Last Frame")


def _complete_attempt(attempt, history, artifact, last_frame_artifact):
	from joymedia.services.review.admission import REJECTED, gate_attempt

	# Admission may reload the Attempt after committing its review evidence.
	# Preserve timings collected during Comfy execution and output ingestion.
	try:
		pre_review_timing = frappe.parse_json(attempt.get("timing_json") or "{}") or {}
	except (TypeError, ValueError):
		pre_review_timing = {}
	if not isinstance(pre_review_timing, dict):
		pre_review_timing = {}
	review_start = time.monotonic()
	try:
		review = gate_attempt(attempt, artifact, history, last_frame_artifact)
	except ValueError as exc:
		for stage, seconds in pre_review_timing.items():
			record_timing(attempt, stage, seconds)
		record_timing(attempt, "visual_admission_seconds", time.monotonic() - review_start)
		return _fail_attempt(attempt, REJECTED, REJECTED + ": " + str(exc), "Input", history=history)
	for stage, seconds in pre_review_timing.items():
		record_timing(attempt, stage, seconds)
	if review and review.get("status") == "Checking":
		if hasattr(attempt, "db_set") and attempt.get("timing_json"):
			attempt.db_set("timing_json", attempt.timing_json, update_modified=False)
		return {"status": "Running", "visual_admission": "Checking"}
	record_timing(attempt, "visual_admission_seconds", time.monotonic() - review_start)
	if review and review.get("status") != "Passed" and not review.get("review_only"):
		from joymedia.services.review.admission import quality_retry

		return _fail_attempt(
			attempt, REJECTED, REJECTED, "Generation" if quality_retry(attempt) else "Input", history=history
		)
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


def _find_last_frame_image(history, workflow=None):
	node_key = "save_last_frame"
	if workflow:
		try:
			spec = frappe.parse_json(getattr(workflow, "execution_spec", None) or "{}")
		except (TypeError, ValueError):
			spec = {}
		node_key = str((((spec.get("outputs") or {}).get("last_frame") or {}).get("node_key")) or node_key)
	node_output = (history.get("outputs") or {}).get(node_key, {})
	for output in node_output.get("images", []):
		filename = str(output.get("filename", "")).lower()
		if filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".avif")):
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


def _create_primary_artifact(attempt, workflow=None):
	workflow = workflow or _attempt_workflow(attempt)
	role = getattr(workflow, "primary_artifact_role", None) or "Primary Video"
	media_type = getattr(workflow, "output_media_type", None) or "Video"
	artifact_key = f"{attempt.name}:{frappe.scrub(role)}"
	existing = get_attempt_artifact(attempt.name, role)
	if existing:
		return existing

	artifact = frappe.get_doc(
		{
			"doctype": "Generation Artifact",
			"artifact_key": artifact_key,
			"artifact_role": role,
			"generation_attempt": attempt.name,
			"media_type": media_type,
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
		output = _find_primary_output(history, _attempt_workflow(attempt))
	if not output:
		frappe.throw(_("Generation Artifact {0} has no available primary output.").format(artifact.name))

	video_bytes = download_output(
		output["filename"],
		output.get("subfolder", ""),
		output.get("type", "output"),
		base_url=attempt.comfyui_endpoint_url,
	)
	lock = {}
	precheck = None
	if artifact.media_type == "Image":
		from joymedia.services.keyframes.overlay import paste_subjects_into_keyframe
		from joymedia.services.review.admission import precheck_image

		precheck = precheck_image(attempt, artifact, video_bytes)
		if not precheck:
			video_bytes = paste_subjects_into_keyframe(attempt, video_bytes, lock=lock)

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
	if lock.get("items"):
		from joymedia.services.keyframes.overlay import store_product_lock

		artifact.product_lock_json = store_product_lock(artifact, lock)
	elif lock.get("unprotected"):
		import json

		# Recorded so review and finishing know the label was not locked.
		artifact.product_lock_json = json.dumps(
			{"canvas": lock.get("canvas"), "items": [], "unprotected": lock["unprotected"]}
		)
	artifact.save(ignore_permissions=True)
	if precheck:
		from joymedia.services.review.admission import store_report

		store_report(attempt, artifact, precheck)
	return artifact


def _refresh_parent_execution_state(attempt_name):
	from joymedia.services.generation.orchestrator import refresh_generation_state_for_attempt

	refresh_generation_state_for_attempt(attempt_name)


def _execution_timestamp(history, message_name):
	for name, details in history.get("status", {}).get("messages", []):
		if name == message_name and details.get("timestamp"):
			# Frappe stores naive datetimes in the system time zone, not UTC.
			utc = datetime.fromtimestamp(details["timestamp"] / 1000, tz=UTC)
			return convert_utc_to_system_timezone(utc).replace(tzinfo=None)
	return None


def _find_primary_output(history, workflow, preferred_node_keys=None):
	media_type = getattr(workflow, "output_media_type", "Video") if workflow else "Video"
	extensions = {
		"Video": (".mp4", ".webm", ".mov", ".mkv"),
		"Image": (".png", ".jpg", ".jpeg", ".webp", ".avif"),
		"Audio": (".wav", ".mp3", ".flac", ".ogg", ".m4a"),
	}.get(media_type, ())
	return _find_output_by_extensions(history, extensions, preferred_node_keys)


def _find_output_by_extensions(history, extensions, preferred_node_keys=None):
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
			+ node_outputs.get("audio", [])
		):
			if str(output.get("filename", "")).lower().endswith(extensions):
				return output
	return None


def _attempt_workflow(attempt):
	workflow_name = (
		frappe.db.get_value("Generation Task", attempt.generation_task, "workflow")
		if getattr(attempt, "generation_task", None)
		else None
	)
	return frappe.get_doc("Generation Workflow", workflow_name) if workflow_name else None
