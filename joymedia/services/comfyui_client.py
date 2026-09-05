from pathlib import Path, PurePosixPath
import uuid

import frappe
import requests
from frappe import _

DEFAULT_TIMEOUT = 60


def get_base_url():
	base_url = frappe.conf.get("comfyui_base_url")
	if not base_url:
		frappe.throw(_("comfyui_base_url is not configured."))
	return base_url.rstrip("/")


def get_input_dir():
	return frappe.conf.get("comfyui_input_dir", "/home/ubuntu/ComfyUI/input")


def upload_frappe_file(file_url: str) -> dict:
	if not file_url:
		frappe.throw(_("File URL is required."))

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	local_path = file_doc.get_full_path()
	if not Path(local_path).exists():
		frappe.throw(_("Local file does not exist: {0}").format(local_path))

	try:
		with open(local_path, "rb") as file_handle:
			response = requests.post(
				f"{get_base_url()}/upload/image",
				files={"image": (Path(local_path).name, file_handle)},
				data={"type": "input", "overwrite": "true"},
				timeout=DEFAULT_TIMEOUT,
			)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))

	_raise_for_comfyui_error(response)
	result = response.json()
	name = result["name"]
	subfolder = result.get("subfolder", "")
	server_path = PurePosixPath(get_input_dir())
	if subfolder:
		server_path /= subfolder
	server_path /= name

	return {**result, "server_path": str(server_path)}


def submit_workflow(workflow: dict) -> dict:
	client_id = str(uuid.uuid4())
	try:
		response = requests.post(
			f"{get_base_url()}/prompt",
			json={"prompt": workflow, "client_id": client_id},
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	result = response.json()
	if not result.get("prompt_id"):
		frappe.throw(_("ComfyUI did not return prompt_id."))
	return result


def get_history(prompt_id: str) -> dict:
	try:
		response = requests.get(
			f"{get_base_url()}/history/{prompt_id}",
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.json()


def download_output(filename: str, subfolder: str = "", file_type: str = "output") -> bytes:
	try:
		response = requests.get(
			f"{get_base_url()}/view",
			params={"filename": filename, "subfolder": subfolder, "type": file_type},
			timeout=120,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.content


def _raise_for_comfyui_error(response):
	if response.ok:
		return
	try:
		details = response.json()
	except Exception:
		details = response.text
	frappe.throw(_("ComfyUI request failed ({0}): {1}").format(response.status_code, details))
