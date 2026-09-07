import frappe

from .worker_monitor import get_active_job_count


def get_model_cache_key(workflow_version_name: str) -> str:
	workflow_version = frappe.get_doc("Workflow Version", workflow_version_name)
	model_cache_key = (workflow_version.model_cache_key or "").strip()
	return model_cache_key or workflow_version.name


def select_worker(workflow_version_name: str):
	"""Choose a healthy, under-capacity worker, preferring confirmed warm residency."""
	model_cache_key = get_model_cache_key(workflow_version_name)
	workers = _get_routable_workers()
	if not workers:
		return None

	for worker in workers:
		worker.active_jobs = get_active_job_count(worker.name)

	available_workers = [
		worker
		for worker in workers
		if worker.active_jobs < max(1, int(worker.max_concurrent_jobs or 1))
	]
	if not available_workers:
		return None

	return min(
		available_workers,
		key=lambda worker: (
			_cache_affinity_rank(worker, model_cache_key),
			worker.active_jobs / max(1, int(worker.max_concurrent_jobs or 1)),
			int(worker.routing_priority or 100),
			worker.name,
		),
	)


def has_configured_workers():
	"""Whether this site has opted into managed ComfyUI Worker routing."""
	return bool(frappe.db.exists("ComfyUI Worker"))


def get_worker(worker_name: str | None):
	if not worker_name:
		return None
	return frappe.get_doc("ComfyUI Worker", worker_name)


def _get_routable_workers():
	workers = frappe.get_all(
		"ComfyUI Worker",
		filters={"status": "Active", "health_status": "Healthy"},
		fields=[
			"name",
			"endpoint_url",
			"input_dir",
			"model_cache_key",
			"observed_model_cache_key",
			"max_concurrent_jobs",
			"routing_priority",
		],
	)
	return [frappe._dict(worker) for worker in workers]


def _cache_affinity_rank(worker, model_cache_key: str):
	if worker.observed_model_cache_key == model_cache_key:
		return 0
	if worker.model_cache_key == model_cache_key:
		return 1
	if not worker.model_cache_key:
		return 2
	return 3
