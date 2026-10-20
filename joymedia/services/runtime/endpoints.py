"""Resolve the application's OpenAI-compatible service endpoints.

The production pipeline calls services by capability (``planner``, ``vision`` and
``translator``), never by a particular vendor or model.  A site config may provide
these neutral objects::

    "joymedia_planner": {"base_url": "http://…/v1", "model": "…", "timeout": 600}
    "joymedia_vision": {"base_url": "http://…/v1", "model": "…", "timeout": 120}
    "joymedia_translator": {"base_url": "http://…/v1", "model": "…"}

``translator`` does the tasks that must stay faithful to the client's words (translation, a rewrite of a scene's own
text, reading its place). A planner fine-tuned to write advertising copy embellishes them ("hero product in f&b…"),
so a plain instruction model belongs here; without one, the planner is used.

The legacy scalar keys remain readable during deployment migration.  They are an
input-compatibility boundary only; no caller should depend on their names.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import frappe
from frappe import _

DEFAULT_TIMEOUTS = {"planner": 600, "vision": 120, "translator": 300}
_LEGACY_KEYS = {
	"planner": {"base_url": "qwen_base_url", "model": "qwen_model", "timeout": "qwen_timeout", "max_model_len": "qwen_max_model_len"},
	"vision": {"base_url": "qwen_vl_base_url", "model": "qwen_vl_model", "timeout": "qwen_vl_timeout"},
	"translator": {},
}
# Capabilities that use another one's endpoint when they have none of their own.
_FALLBACK = {"translator": "planner"}


def is_configured(capability: str) -> bool:
	"""Whether a complete endpoint is configured for ``capability``."""
	try:
		endpoint(capability)
	except frappe.ValidationError:
		return False
	return True


def endpoint(capability: str) -> frappe._dict:
	"""Return validated endpoint details for a logical service capability.

	The result has ``base_url``, ``model`` and ``timeout``.  Optional endpoint
	settings (such as ``max_model_len``) are retained so capability consumers can
	use them without knowing the configured model.
	"""
	if capability not in DEFAULT_TIMEOUTS:
		raise ValueError(f"Unsupported JoyMedia service capability: {capability}")
	configured = frappe.conf.get(f"joymedia_{capability}")
	if not configured and capability in _FALLBACK:
		return endpoint(_FALLBACK[capability])
	if configured and not isinstance(configured, Mapping):
		frappe.throw(_("joymedia_{0} must be an object.").format(capability))
	values = dict(configured or {})
	legacy = _LEGACY_KEYS[capability]
	for key, legacy_key in legacy.items():
		values.setdefault(key, frappe.conf.get(legacy_key))
	base_url = str(values.get("base_url") or "").strip().rstrip("/")
	model = str(values.get("model") or "").strip()
	if not base_url:
		frappe.throw(_("JoyMedia {0} endpoint base_url is not configured.").format(capability))
	if not model:
		frappe.throw(_("JoyMedia {0} endpoint model is not configured.").format(capability))
	try:
		timeout = float(values.get("timeout") or DEFAULT_TIMEOUTS[capability])
	except (TypeError, ValueError):
		frappe.throw(_("JoyMedia {0} endpoint timeout must be a positive number of seconds.").format(capability))
	if not math.isfinite(timeout) or timeout <= 0:
		frappe.throw(_("JoyMedia {0} endpoint timeout must be a positive number of seconds.").format(capability))
	values.update(base_url=base_url, model=model, timeout=timeout)
	return frappe._dict(values)


def planner_context_window(default: int) -> int:
	"""Return the configured planner context window, with a safe positive default."""
	try:
		value = int(endpoint("planner").get("max_model_len") or default)
	except (TypeError, ValueError):
		return default
	return value if value > 0 else default


def structured_response(configured, schema, name):
	"""Encode a schema for an explicitly configured HTTP transport, never a model name."""
	options = configured.get("structured_output")
	if options is None:
		options = {}
	if not isinstance(options, Mapping):
		raise ValueError("structured_output must be an object.")
	transport = options.get("transport", "response_format")
	if transport == "response_format":
		return {"response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}}
	if transport == "structured_outputs":
		compact = options.get("compact", True)
		if type(compact) is not bool:
			raise ValueError("structured_output compact must be a boolean.")
		return {"structured_outputs": {"json": schema, "disable_any_whitespace": compact}}
	raise ValueError("Unsupported structured output transport.")
