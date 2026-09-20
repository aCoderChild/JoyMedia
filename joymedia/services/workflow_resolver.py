import copy
import hashlib
import json

import frappe
from frappe import _

from joymedia.workflow_adapters.base import canonical_workflow_json


_SKIP_BINDING = object()


def resolve_attempt(attempt_name: str, staged_inputs=None):
	staged_inputs = staged_inputs or {}
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	job = frappe.get_doc("Generation Job", attempt.generation_job)
	workflow_version = frappe.get_doc("Workflow Version", job.workflow_version)
	compiled_prompt = frappe.get_doc("Compiled Prompt", job.compiled_prompt)

	try:
		base_workflow = json.loads(workflow_version.workflow_json)
	except json.JSONDecodeError as exc:
		frappe.throw(_("Invalid Workflow JSON: {0}").format(str(exc)))

	workflow = copy.deepcopy(base_workflow)
	for binding in workflow_version.bindings:
		value = _resolve_binding(binding, job, attempt, compiled_prompt, staged_inputs)
		node = workflow.get(binding.node_key)
		if node is None or binding.input_name not in node.get("inputs", {}):
			frappe.throw(_("Invalid Workflow Binding: {0}").format(binding.binding_key))
		if value is _SKIP_BINDING:
			continue
		node["inputs"][binding.input_name] = value

	canonical = canonical_workflow_json(workflow)
	attempt.resolved_workflow_json = json.dumps(workflow, indent=2, ensure_ascii=False)
	attempt.resolved_workflow_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
	attempt.save()
	return workflow


def _resolve_binding(binding, job, attempt, compiled_prompt, staged_inputs):
	if binding.value_source == "Generation Input":
		return _resolve_generation_input(
			job,
			binding.required_input_role,
			staged_inputs,
			required=bool(binding.required),
		)
	if binding.value_source == "Compiled Prompt":
		return compiled_prompt.prompt_text
	if binding.value_source == "Attempt Seed":
		return int(attempt.seed)
	if binding.value_source == "Runtime Value":
		return _resolve_runtime_value(binding.binding_key, job, attempt)
	if binding.value_source == "Job Value":
		return _resolve_job_value(binding.binding_key, job)
	frappe.throw(_("Unsupported Workflow Binding Value Source: {0}").format(binding.value_source))


def _resolve_generation_input(job, required_role, staged_inputs, required=True):
	if not required_role:
		frappe.throw(_("Generation Input binding requires Required Input Role."))
	normalized_role = frappe.scrub(required_role)
	staged_value = staged_inputs.get(normalized_role)
	if staged_value:
		return staged_value
	if not required:
		return _SKIP_BINDING
	frappe.throw(
		_("No staged ComfyUI input found for role '{0}' on Generation Job {1}.").format(
			normalized_role, job.name
		)
	)


def _resolve_runtime_value(binding_key, job, attempt):
	if binding_key == "output_filename_prefix":
		return f"{job.name}_{attempt.name}"
	if binding_key in {"delivery_width", "delivery_height"}:
		shot = frappe.get_doc("Shot Specification", job.shot_specification)
		media_spec = frappe.get_doc("Media Specification", shot.media_specification)
		if binding_key == "delivery_width":
			return int(media_spec.delivery_width)
		return int(media_spec.delivery_height)
	if binding_key == "segment_last_frame_index":
		return int(job.segment_frame_count) - 1
	if binding_key == "last_frame_filename_prefix":
		return f"{job.name}_{attempt.name}_last_frame"
	frappe.throw(_("Unsupported Runtime Value binding: {0}").format(binding_key))


def _resolve_job_value(binding_key, job):
	if not hasattr(job, binding_key):
		frappe.throw(_("Generation Job does not contain field '{0}'.").format(binding_key))
	return getattr(job, binding_key)
