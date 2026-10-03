from pathlib import Path
import uuid

import frappe
import requests
from frappe import _

DEFAULT_TIMEOUT = 60


def get_base_url(base_url: str | None = None):
	base_url = base_url or frappe.conf.get("comfyui_base_url")
	if not base_url:
		frappe.throw(_("comfyui_base_url is not configured."))
	return base_url.rstrip("/")


def get_request_auth():
	username = frappe.conf.get("comfyui_username")
	password = frappe.conf.get("comfyui_password")
	if not username and not password:
		return None
	if not username or not password:
		frappe.throw(_("Both comfyui_username and comfyui_password must be configured."))
	return username, password


def upload_frappe_file(file_url: str, *, base_url: str | None = None, input_dir: str | None = None) -> dict:
	if not file_url:
		frappe.throw(_("File URL is required."))

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	local_path = file_doc.get_full_path()
	if not Path(local_path).exists():
		frappe.throw(_("Local file does not exist: {0}").format(local_path))

	try:
		comfyui_filename = f"joymedia_{uuid.uuid4().hex}{Path(local_path).suffix.lower()}"
		with open(local_path, "rb") as file_handle:
			response = requests.post(
				f"{get_base_url(base_url)}/upload/image",
				files={"image": (comfyui_filename, file_handle)},
				data={"type": "input", "overwrite": "true"},
				auth=get_request_auth(),
				timeout=DEFAULT_TIMEOUT,
			)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))

	_raise_for_comfyui_error(response)
	result = response.json()
	name = result["name"]
	subfolder = result.get("subfolder", "")
	server_path = "/".join(part for part in (str(subfolder).strip("/"), name) if part)

	return {**result, "server_path": server_path}


def submit_workflow(workflow: dict, *, base_url: str | None = None) -> dict:
	client_id = str(uuid.uuid4())
	try:
		response = requests.post(
			f"{get_base_url(base_url)}/prompt",
			json={"prompt": workflow, "client_id": client_id},
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	result = response.json()
	if not result.get("prompt_id"):
		frappe.throw(_("ComfyUI did not return prompt_id."))
	return result


def get_history(prompt_id: str, *, base_url: str | None = None) -> dict:
	try:
		response = requests.get(
			f"{get_base_url(base_url)}/history/{prompt_id}",
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.json()


def get_queue(*, base_url: str | None = None) -> dict:
	try:
		response = requests.get(
			f"{get_base_url(base_url)}/queue",
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.json()


def delete_queue_prompts(prompt_ids: list[str], *, base_url: str | None = None) -> dict:
	if not prompt_ids:
		return {}
	try:
		response = requests.post(
			f"{get_base_url(base_url)}/queue",
			json={"delete": prompt_ids},
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.json() if response.content else {}


def interrupt(*, prompt_id: str | None = None, base_url: str | None = None) -> dict:
	if not prompt_id:
		frappe.throw(_("A ComfyUI prompt ID is required to interrupt a job."))
	try:
		response = requests.post(
			f"{get_base_url(base_url)}/interrupt",
			json={"prompt_id": prompt_id},
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.json() if response.content else {}


def get_queue_state(prompt_id: str, *, base_url: str | None = None) -> str | None:
	"""Return "running", "pending", or None when the prompt is not in the ComfyUI queue."""
	queue = get_queue(base_url=base_url)
	for state, key in (("running", "queue_running"), ("pending", "queue_pending")):
		# ComfyUI queue items are [number, prompt_id, prompt, extra_data, outputs_to_execute].
		if any(len(item) > 1 and item[1] == prompt_id for item in queue.get(key) or []):
			return state
	return None


def get_system_stats(*, base_url: str | None = None) -> dict:
	try:
		response = requests.get(
			f"{get_base_url(base_url)}/system_stats",
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.json()


def download_output(
	filename: str, subfolder: str = "", file_type: str = "output", *, base_url: str | None = None
) -> bytes:
	try:
		response = requests.get(
			f"{get_base_url(base_url)}/view",
			params={"filename": filename, "subfolder": subfolder, "type": file_type},
			auth=get_request_auth(),
			timeout=120,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.content


def probe_output(filename: str, subfolder: str = "", file_type: str = "output", *, base_url: str | None = None) -> bool:
	"""Check whether ComfyUI already wrote a deterministic output file."""
	try:
		response = requests.get(
			f"{get_base_url(base_url)}/view",
			params={"filename": filename, "subfolder": subfolder, "type": file_type},
			auth=get_request_auth(),
			timeout=10,
		)
		return response.ok and bool(response.content)
	except requests.RequestException:
		return False


def _raise_for_comfyui_error(response):
	if response.ok:
		return
	try:
		details = response.json()
	except Exception:
		details = response.text
	frappe.throw(_("ComfyUI request failed ({0}): {1}").format(response.status_code, details))
