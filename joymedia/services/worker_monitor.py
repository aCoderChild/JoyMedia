import frappe
from frappe.utils import now

from .comfyui_client import get_system_stats


MIB = 1024 * 1024


def refresh_workers():
	"""Refresh health and device telemetry for all enabled ComfyUI workers."""
	if not frappe.db.exists("DocType", "ComfyUI Worker"):
		return

	for worker_name in frappe.get_all("ComfyUI Worker", filters={"status": "Active"}, pluck="name"):
		try:
			refresh_worker(worker_name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.logger("joymedia.worker_monitor").exception(
				"Unable to refresh ComfyUI Worker %s", worker_name
			)


def refresh_worker(worker_name: str):
	"""Use ComfyUI system statistics for connectivity and GPU telemetry only."""
	worker = frappe.get_doc("ComfyUI Worker", worker_name)
	if worker.status != "Active":
		return worker

	try:
		stats = get_system_stats(base_url=worker.endpoint_url)
		device = (stats.get("devices") or [None])[0]
		if not device:
			raise ValueError("ComfyUI did not report a GPU device")
	except Exception:
		if worker.health_status != "Draining":
			worker.health_status = "Offline"
		worker.active_jobs = get_active_job_count(worker.name)
		worker.save(ignore_permissions=True)
		raise

	if worker.health_status != "Draining":
		worker.health_status = "Healthy"
	worker.last_heartbeat_at = now()
	worker.gpu_name = device.get("name") or None
	worker.vram_total_mib = _to_mib(device.get("vram_total"))
	worker.vram_free_mib = _to_mib(device.get("vram_free"))
	worker.active_jobs = get_active_job_count(worker.name)
	worker.save(ignore_permissions=True)
	return worker


def get_active_job_count(worker_name: str) -> int:
	return frappe.db.count(
		"Generation Attempt",
		filters={"comfyui_worker": worker_name, "status": ["in", ["Queued", "Running"]]},
	)


def record_observed_model_cache_key(worker_name: str, observed_model_cache_key: str | None):
	"""Persist model-residency telemetry supplied by a trusted worker-side integration.

	ComfyUI's stock system statistics endpoint has no loaded-model field, so this
	function deliberately does not infer residency from a submission or VRAM level.
	"""
	worker = frappe.get_doc("ComfyUI Worker", worker_name)
	worker.observed_model_cache_key = (observed_model_cache_key or "").strip() or None
	worker.save(ignore_permissions=True)
	return worker


def _to_mib(value):
	try:
		return round(float(value) / MIB, 2)
	except (TypeError, ValueError):
		return None
