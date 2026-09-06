import frappe


def get_model_cache_key(workflow_version_name: str) -> str:
	workflow_version = frappe.get_doc("Workflow Version", workflow_version_name)
	model_cache_key = (workflow_version.model_cache_key or "").strip()
	return model_cache_key or workflow_version.name


def select_worker(workflow_version_name: str):
	"""Return the deterministic active worker for a workflow's cache key, if configured."""
	model_cache_key = get_model_cache_key(workflow_version_name)
	worker = _find_active_worker(model_cache_key)
	return worker or _find_active_worker("")


def get_worker(worker_name: str | None):
	if not worker_name:
		return None
	return frappe.get_doc("ComfyUI Worker", worker_name)


def _find_active_worker(model_cache_key: str):
	workers = frappe.get_all(
		"ComfyUI Worker",
		filters={"status": "Active", "model_cache_key": model_cache_key},
		fields=["name", "endpoint_url", "input_dir", "model_cache_key"],
		order_by="routing_priority asc, name asc",
		limit_page_length=1,
	)
	return frappe._dict(workers[0]) if workers else None
