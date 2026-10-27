"""Classifies a failed attempt and turns a technical error into a message a customer can act on."""

import re

from frappe import _

_COMFY_EXCEPTION = re.compile(r"exception_message['\"]?\s*[:=]\s*['\"]([^'\"]+)", re.I)


def classify_failure(error, default="Unknown"):
	message = str(error or "")
	lower_message = message.lower()
	if "cancel" in lower_message:
		return "Cancelled"
	# An interrupted ComfyUI execution says nothing about the workflow; its status
	# log merely lists cached "nodes". Render the scene again.
	if "execution_interrupted" in lower_message:
		return "Infrastructure"
	# Provider/node authentication cannot be fixed by submitting the same prompt
	# again.  Treat it as a workflow configuration issue so the UI asks for the
	# integration to be connected instead of claiming the render is still queued.
	if any(
		token in lower_message
		for token in ("unauthorized", "forbidden", "please login", "authentication", "not authenticated")
	):
		return "Workflow"
	if "workflow" in lower_message or "node" in lower_message:
		return "Workflow"
	if "input" in lower_message or "reference" in lower_message or "asset" in lower_message:
		return "Input"
	if "comfyui" in lower_message or "queue" in lower_message or "connect" in lower_message:
		return "Infrastructure"
	return default


def technical_message(error):
	"""Extract a useful ComfyUI exception without exposing its full message dump."""
	message = str(error or "")
	match = _COMFY_EXCEPTION.search(message)
	return match.group(1).strip() if match else message[:500]


def friendly_failure(failure_class, error_summary=None):
	if str(error_summary or "").startswith("Visual admission rejected"):
		return _(
			"Automatic visual checks held this scene. Your previous video is preserved; the administrator can inspect the recorded evidence."
		)
	if failure_class == "Workflow" and any(
		token in str(error_summary or "").lower()
		for token in ("unauthorized", "forbidden", "please login", "authentication", "not authenticated")
	):
		return _(
			"The image-generation provider is not connected. Ask an administrator to sign in, then retry."
		)
	messages = {
		"Infrastructure": "The render server dropped this job. It is safe to try again.",
		"Workflow": "The selected video setup is unavailable. Please try again or contact support.",
		"Input": "One of the selected media inputs is not usable for this scene.",
		"Generation": "The scene could not be rendered. Please try again.",
		"Finalization": "The rendered scene needs a correction before it can be used.",
		"Cancelled": "Rendering was stopped.",
		"Unknown": "The scene could not be completed. Please try again.",
	}
	return _(messages.get(failure_class or "Unknown", messages["Unknown"]))
