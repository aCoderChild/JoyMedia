"""Provider-neutral contracts; declarations describe controls, never promise identity.

Workflow records are the deployment boundary. Unknown models need no application
branch: their capacity, controls and bindings belong to the immutable record.
"""

import math


def execution_spec(workflow):
	import json

	value = (
		workflow.get("execution_spec")
		if hasattr(workflow, "get")
		else getattr(workflow, "execution_spec", None)
	)
	spec = json.loads(value or "{}") if isinstance(value, str) else (value or {})
	if not isinstance(spec, dict):
		raise ValueError("Workflow execution_spec must be an object.")
	return spec


def capacity(workflow):
	spec = execution_spec(workflow)
	value = (spec.get("limits") or {}).get("max_frames", workflow.get("frame_count"))
	if (
		isinstance(value, bool)
		or not isinstance(value, (int, float))
		or not math.isfinite(value)
		or int(value) != value
		or value < 1
	):
		raise ValueError("Workflow max_frames must be a positive integer.")
	return int(value)


def controls(workflow):
	declared = execution_spec(workflow).get("capabilities") or []
	if not isinstance(declared, list) or any(not isinstance(v, str) or not v.strip() for v in declared):
		raise ValueError("Workflow capabilities must be a list of nonempty names.")
	return frozenset(declared)


def validate_contract(spec):
	controls({"execution_spec": spec})
	limits = spec.get("limits", {})
	if not isinstance(limits, dict):
		raise ValueError("Workflow limits must be an object.")
	if set(limits) - {"max_frames"}:
		raise ValueError("Unsupported workflow limit; supported: max_frames.")
	if "max_frames" in limits:
		capacity({"execution_spec": spec})


def require_controls(workflow, required):
	missing = set(required) - controls(workflow)
	if missing:
		raise ValueError("Workflow lacks required controls: " + ", ".join(sorted(missing)))


def configured_workflow(capability, *, legacy_key=None):
	"""Resolve an explicitly configured version, never the newest arbitrary model.

	Legacy keys are migration defaults. New deployments pin a workflow version in
	joymedia_workflows, so registration cannot silently change a project's provider.
	"""
	import frappe

	configured = frappe.conf.get("joymedia_workflows") or {}
	if not isinstance(configured, dict):
		raise ValueError("joymedia_workflows must map capabilities to workflow versions.")
	name = configured.get(capability)
	if name:
		if not frappe.db.exists("Generation Workflow", name):
			raise ValueError(f"Configured {capability} workflow does not exist: {name}")
		return name
	return (
		frappe.db.get_value(
			"Generation Workflow", {"workflow_key": legacy_key}, "name", order_by="version_number desc"
		)
		if legacy_key
		else None
	)
