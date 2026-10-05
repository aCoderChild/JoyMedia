import re

from frappe import _


_COMFY_EXCEPTION = re.compile(r"exception_message['\"]?\s*[:=]\s*['\"]([^'\"]+)", re.I)


def classify_failure(error, default="Unknown"):
	message = str(error or "")
	if "cancel" in message.lower():
		return "Cancelled"
	if "workflow" in message.lower() or "node" in message.lower():
		return "Workflow"
	if "input" in message.lower() or "reference" in message.lower() or "asset" in message.lower():
		return "Input"
	if "comfyui" in message.lower() or "queue" in message.lower() or "connect" in message.lower():
		return "Infrastructure"
	return default


def technical_message(error):
	"""Extract a useful ComfyUI exception without exposing its full message dump."""
	message = str(error or "")
	match = _COMFY_EXCEPTION.search(message)
	return match.group(1).strip() if match else message[:500]


def friendly_failure(failure_class, error_summary=None):
	messages = {
		"Infrastructure": "The render server dropped this job. It is safe to try again.",
		"Workflow": "The selected video setup is unavailable. Please try again or contact support.",
		"Input": "One of the selected media inputs is not usable for this scene.",
		"Generation": "The scene could not be rendered. Please try again.",
		"Cancelled": "Rendering was stopped.",
		"Unknown": "The scene could not be completed. Please try again.",
	}
	return _(messages.get(failure_class or "Unknown", messages["Unknown"]))
