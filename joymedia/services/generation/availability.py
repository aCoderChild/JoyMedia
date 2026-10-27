"""Fast admission check for partner batches that may wait for an offline GPU."""

import frappe
import requests


def partner_gpu_ready():
	"""Require all configured remote services before starting partner automation.

	This is an admission check, not a guarantee that a long render cannot lose
	its connection later. Existing attempt reconciliation handles that case.
	"""
	from joymedia.services.workflows.comfyui import get_control_url

	urls = []
	for key in ("joymedia_planner", "joymedia_vision"):
		config = frappe.conf.get(key) or {}
		if isinstance(config, str):
			config = frappe.parse_json(config) or {}
		base = config.get("base_url") if isinstance(config, dict) else None
		if not base:
			return False
		urls.append((base.rstrip("/") + "/models", "data"))
	if not frappe.conf.get("comfyui_base_url"):
		return False
	urls.append((get_control_url() + "/system_stats", "system"))
	for url, expected_key in urls:
		try:
			response = requests.get(url, timeout=(1, 2))
			response.raise_for_status()
			body = response.json()
			if not isinstance(body, dict) or expected_key not in body:
				return False
		except (requests.RequestException, ValueError):
			return False
	return True


def partner_batch_waits_for_gpu(owner):
	from joymedia.services.partners import is_reviewer

	return is_reviewer(owner) and not partner_gpu_ready()
