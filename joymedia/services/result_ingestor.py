from pathlib import Path
from datetime import datetime, timezone

import frappe
from frappe import _
from frappe.utils import get_datetime, now

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
	if attempt.output_asset_version and attempt.status == "Completed":
		return {
			"status": attempt.status,
			"output_asset_version": attempt.output_asset_version,
		}
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
		return {"status": attempt.status}

	if not status.get("completed"):
		if status_string == "executing":
			attempt.status = "Running"
			if not attempt.started_at:
				attempt.started_at = now()
		else:
			attempt.status = "Queued"
		attempt.save(ignore_permissions=True)
		return {"status": attempt.status}

	output = _find_primary_mp4(history)
	if not output:
		frappe.throw(_("ComfyUI completed without a primary MP4 output."))

	video_bytes = download_output(
		output["filename"], output.get("subfolder", ""), output.get("type", "output"), base_url=base_url
	)
	job = frappe.get_doc("Generation Job", attempt.generation_job)
	shot = frappe.get_doc("Shot Specification", job.shot_specification)
	media_spec = frappe.get_doc("Media Specification", shot.media_specification)

	asset_name = f"{shot.name} Generated Video"
	asset_name = frappe.db.get_value("Media Asset", {"asset_name": asset_name}, "name")
	if asset_name:
		output_asset = frappe.get_doc("Media Asset", asset_name)
	else:
		output_asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": f"{shot.name} Generated Video",
				"asset_scope": "Project",
				"media_type": "Video",
				"asset_category": "Shot Output",
				"media_project": media_spec.media_project,
			}
		)
		output_asset.insert(ignore_permissions=True)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": Path(output["filename"]).name,
			"content": video_bytes,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": output_asset.name,
		}
	)
	file_doc.insert(ignore_permissions=True)

	asset_version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": output_asset.name,
			"file": file_doc.file_url,
			"source": "Generated",
		}
	)
	asset_version.insert(ignore_permissions=True)

	attempt.output_asset_version = asset_version.name
	attempt.status = "Completed"
	if not attempt.started_at:
		attempt.started_at = _execution_timestamp(history, "execution_start") or now()
	attempt.completed_at = now()
	if attempt.started_at:
		attempt.runtime_seconds = max(
			0, (get_datetime(attempt.completed_at) - get_datetime(attempt.started_at)).total_seconds()
		)
	attempt.save(ignore_permissions=True)
	_auto_select_single_variant_output(job, shot, asset_version.name)
	return {"status": attempt.status, "output_asset_version": asset_version.name}


def _auto_select_single_variant_output(job, shot, asset_version_name):
	if job.requested_variants != 1:
		return

	shot.selected_output_asset_version = asset_version_name
	shot.save(ignore_permissions=True)


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
