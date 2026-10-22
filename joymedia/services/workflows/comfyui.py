"""HTTP client of the shared ComfyUI server: upload input files, submit a prompt, read history and queue,
interrupt or delete jobs, download outputs. Nothing else in the app talks to ComfyUI directly.
"""

import time
import uuid
from pathlib import Path

import frappe
import requests
from frappe import _
from frappe.utils.synchronization import filelock

# The shared GPU server can take over a minute to answer while it is under load.
DEFAULT_TIMEOUT = 180
# Consecutive failed history polls (5 s apart) tolerated while a job runs.
MAX_POLL_FAILURES = 24
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def get_base_url(base_url: str | None = None):
	base_url = base_url or frappe.conf.get("comfyui_base_url")
	if not base_url:
		frappe.throw(_("comfyui_base_url is not configured."))
	return base_url.rstrip("/")


def endpoint_for_workflow(workflow_name):
	"""Operator routing is frozen on each attempt before uploads or submission."""
	from urllib.parse import urlsplit

	routes = frappe.conf.get("joymedia_workflow_endpoints") or {}
	if not isinstance(routes, dict):
		raise ValueError("joymedia_workflow_endpoints must map workflow versions to HTTP(S) endpoints.")
	value = routes.get(workflow_name)
	if value is None:
		return get_base_url()
	if not isinstance(value, str):
		raise ValueError("A workflow endpoint must be an HTTP(S) URL.")
	url = urlsplit(value)
	if (
		url.scheme not in {"http", "https"}
		or not url.hostname
		or url.username
		or url.password
		or url.query
		or url.fragment
	):
		raise ValueError("A workflow endpoint must be an HTTP(S) URL without credentials, query or fragment.")
	return value.rstrip("/")


def get_control_url(base_url=None):
	"""Explicit alternate transport to the same server for small control calls.

	Only operator-declared logical endpoints are routed. An arbitrary historical
	or alternate server must never be redirected to the current default server.
	"""
	logical = get_base_url(base_url)
	routes = frappe.conf.get("comfyui_control_routes") or {}
	if not isinstance(routes, dict):
		raise ValueError("comfyui_control_routes must map endpoint URLs to control URLs.")
	target = routes.get(logical, logical)
	if not isinstance(target, str) or not target.startswith(("http://", "https://")):
		raise ValueError("A ComfyUI control route must be an HTTP(S) URL.")
	return target.rstrip("/")


def get_request_auth():
	username = frappe.conf.get("comfyui_username")
	password = frappe.conf.get("comfyui_password")
	if not username and not password:
		return None
	if not username or not password:
		frappe.throw(_("Both comfyui_username and comfyui_password must be configured."))
	return username, password


def _transfer_urls(base_url, config_key):
	"""Only an explicitly declared transport of the same server may receive a retry."""
	from urllib.parse import urlsplit

	logical = get_base_url(base_url)
	routes = frappe.conf.get(config_key) or {}
	if not isinstance(routes, dict):
		raise ValueError(f"{config_key} must map endpoint URLs to alternate transports.")
	target = routes.get(logical)
	if target is None:
		return [logical]
	url = urlsplit(target) if isinstance(target, str) else None
	if not url or url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
		raise ValueError("A ComfyUI transfer fallback must be an HTTP(S) transport URL without credentials.")
	target = target.rstrip("/")
	return [logical, target] if target != logical else [logical]


def get_upload_urls(base_url=None):
	return _transfer_urls(base_url, "comfyui_upload_fallback_routes")

def upload_frappe_file(file_url: str, *, base_url: str | None = None, input_dir: str | None = None) -> dict:
	if not file_url:
		frappe.throw(_("File URL is required."))

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	return upload_local_file(file_doc.get_full_path(), base_url=base_url)


def upload_local_file(local_path, *, base_url: str | None = None) -> dict:
	path = Path(local_path)
	if not path.exists():
		frappe.throw(_("Local file does not exist: {0}").format(local_path))
	_validate_image_upload(path)

	# ComfyUI's input endpoint is not safe for bursty parallel multipart uploads.
	# Generation Tasks can run concurrently, but staging their inputs must be
	# serialized across Frappe workers to keep the remote server responsive.
	with filelock("joymedia-comfyui-upload"):
		urls = get_upload_urls(base_url)
		comfyui_filename = f"joymedia_{uuid.uuid4().hex}{path.suffix.lower()}"
		for index, url in enumerate(urls):
			try:
				# Reopen from byte zero and retain one filename: a timed-out upload
				# may already exist on the same server. Prompt submission is not retried here.
				with open(local_path, "rb") as file_handle:
					response = requests.post(
						f"{url}/upload/image",
						files={"image": (comfyui_filename, file_handle)},
						data={"type": "input", "overwrite": "true"},
						auth=get_request_auth(),
						timeout=DEFAULT_TIMEOUT,
					)
				break
			except (requests.ConnectionError, requests.Timeout) as exc:
				if index == len(urls) - 1:
					frappe.throw(_("Unable to upload to ComfyUI: {0}").format(str(exc)))

	_raise_for_comfyui_error(response)
	result = response.json()
	name = result["name"]
	subfolder = result.get("subfolder", "")
	server_path = "/".join(part for part in (str(subfolder).strip("/"), name) if part)

	return {**result, "server_path": server_path}


def _validate_image_upload(path: Path):
	"""Reject corrupt image bytes before they consume a ComfyUI queue slot."""
	if path.suffix.lower() not in IMAGE_SUFFIXES:
		return
	try:
		from PIL import Image

		with Image.open(path) as image:
			image.verify()
	except (OSError, ValueError):
		frappe.throw(_("Input image is invalid and cannot be sent to ComfyUI: {0}").format(path.name))


def submit_workflow(workflow: dict, *, base_url: str | None = None, client_id: str | None = None) -> dict:
	"""Submit once with a caller-owned identity for safe reconciliation."""
	client_id = client_id or str(uuid.uuid4())
	try:
		response = requests.post(
			f"{get_control_url(base_url)}/prompt",
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


def find_prompt_by_client_id(client_id: str, *, base_url: str | None = None) -> str | None:
	"""Find a prompt accepted by ComfyUI before Frappe stored its prompt id.

	ComfyUI preserves client_id in queued prompt extra data and normally in
	history.  This is deliberately generic protocol handling; it does not inspect
	model nodes or filenames.
	"""
	queue = get_queue(base_url=base_url)
	for items in queue.values():
		for item in items or []:
			if len(item) > 3 and isinstance(item[3], dict) and item[3].get("client_id") == client_id:
				return item[1]
	history = get_all_history(base_url=base_url)
	for prompt_id, item in history.items():
		prompt = item.get("prompt") if isinstance(item, dict) else None
		extra = prompt[3] if isinstance(prompt, list) and len(prompt) > 3 else item.get("extra_data", {})
		if isinstance(extra, dict) and extra.get("client_id") == client_id:
			return prompt_id
	return None


def get_all_history(*, base_url: str | None = None) -> dict:
	try:
		response = requests.get(
			f"{get_base_url(base_url)}/history",
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.json()


def get_history(prompt_id: str, *, base_url: str | None = None) -> dict:
	try:
		response = requests.get(
			f"{get_control_url(base_url)}/history/{prompt_id}",
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
			f"{get_control_url(base_url)}/queue",
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
			f"{get_control_url(base_url)}/queue",
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
			f"{get_control_url(base_url)}/interrupt",
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
			f"{get_control_url(base_url)}/system_stats",
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.json()


def get_object_info(*, base_url: str | None = None) -> dict:
	"""Return the node types actually registered by the target ComfyUI server."""
	try:
		response = requests.get(
			f"{get_control_url(base_url)}/object_info",
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	result = response.json()
	if not isinstance(result, dict):
		frappe.throw(_("ComfyUI returned invalid node metadata."))
	return result


def download_output(
	filename: str, subfolder: str = "", file_type: str = "output", *, base_url: str | None = None
) -> bytes:
	urls = _transfer_urls(base_url, "comfyui_download_fallback_routes")
	for index, url in enumerate(urls):
		try:
			response = requests.get(
				f"{url}/view",
				params={"filename": filename, "subfolder": subfolder, "type": file_type},
				auth=get_request_auth(),
				timeout=120,
			)
			break
		except (requests.ConnectionError, requests.Timeout) as exc:
			if index == len(urls) - 1:
				frappe.throw(_("Unable to download from ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)
	return response.content


def run_workflow_to_bytes(
	workflow: dict,
	output_node: str,
	*,
	timeout: float = 3600,
	forget: bool = False,
	base_url: str | None = None,
	on_submitted=None,
) -> bytes:
	"""Run one ComfyUI job to completion and return the first file saved by output_node.

	forget removes the job from the shared ComfyUI history once its output is downloaded.
	"""
	prompt_id = submit_workflow(workflow, base_url=base_url)["prompt_id"]
	if on_submitted:
		on_submitted(prompt_id)
	deadline = time.monotonic() + timeout
	poll_failures = 0
	while time.monotonic() < deadline:
		try:
			history = get_history(prompt_id, base_url=base_url).get(prompt_id)
			poll_failures = 0
		except (requests.RequestException, frappe.ValidationError):
			# A brief network or tunnel drop must not throw away a long render.
			poll_failures += 1
			if poll_failures > MAX_POLL_FAILURES:
				raise
			time.sleep(5)
			continue
		if history:
			status = history.get("status") or {}
			if status.get("status_str") == "error":
				errors = [
					message[1].get("exception_message", "")
					for message in status.get("messages") or []
					if message and message[0] == "execution_error"
				]
				frappe.throw(_("ComfyUI job failed: {0}").format("; ".join(errors) or prompt_id))
			saved = (history.get("outputs") or {}).get(output_node, {})
			for item in (
				saved.get("images", [])
				+ saved.get("videos", [])
				+ saved.get("gifs", [])
				+ saved.get("audio", [])
			):
				content = download_output(
					item["filename"], item.get("subfolder", ""), item.get("type", "output"), base_url=base_url
				)
				if forget:
					delete_history([prompt_id], base_url=base_url)
				return content
			if status.get("completed"):
				frappe.throw(_("ComfyUI job {0} produced no output.").format(prompt_id))
		time.sleep(5)
	interrupt(prompt_id=prompt_id, base_url=base_url)
	frappe.throw(_("ComfyUI job {0} timed out.").format(prompt_id))


def delete_history(prompt_ids: list[str], *, base_url: str | None = None):
	try:
		response = requests.post(
			f"{get_control_url(base_url)}/history",
			json={"delete": prompt_ids},
			auth=get_request_auth(),
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to ComfyUI: {0}").format(str(exc)))
	_raise_for_comfyui_error(response)


def probe_output(
	filename: str, subfolder: str = "", file_type: str = "output", *, base_url: str | None = None
) -> bool:
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
