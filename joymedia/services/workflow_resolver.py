import copy
import hashlib
import json

import frappe
from frappe import _

from joymedia.workflow_adapters import get_workflow_adapter
from joymedia.workflow_adapters.base import canonical_workflow_json


_SKIP_BINDING = object()
SEMANTIC_BINDING_KEYS = {"first_frame", "last_frame", "generation_prompt"}


def resolve_attempt(attempt_name: str, staged_inputs=None):
	staged_inputs = staged_inputs or {}
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	job = frappe.get_doc("Generation Job", attempt.generation_job)
	workflow_version = frappe.get_doc("Generation Workflow", job.workflow_version)
	try:
		base_workflow = json.loads(workflow_version.workflow_json)
	except json.JSONDecodeError as exc:
		frappe.throw(_("Invalid Workflow JSON: {0}").format(str(exc)))

	validate_workflow_for_execution(workflow_version, base_workflow)
	workflow = copy.deepcopy(base_workflow)
	_validate_workflow_bindings(workflow_version, workflow)
	for binding in workflow_version.bindings:
		value = _resolve_semantic_binding(binding, job, staged_inputs)
		node = workflow[binding.node_key]
		if value is _SKIP_BINDING:
			continue
		node["inputs"][binding.input_name] = value

	shot = frappe.get_doc("Shot Specification", job.shot_specification)
	project = frappe.get_doc("Media Project", shot.media_project)
	adapter = get_workflow_adapter(workflow_version)
	adapter.prepare_execution(
		workflow,
		seed=int(attempt.seed),
		width=int(project.delivery_width),
		height=int(project.delivery_height),
		frame_count=int(job.segment_frame_count),
		output_prefix=f"{job.name}_{attempt.name}",
		last_frame_index=int(job.segment_frame_count) - 1,
		last_frame_prefix=f"{job.name}_{attempt.name}_last_frame",
	)

	if any(
		binding.binding_key == "last_frame" and not staged_inputs.get("last_frame")
		for binding in workflow_version.bindings
	):
		adapter.finalize_workflow(workflow, workflow_version, staged_inputs)

	canonical = canonical_workflow_json(workflow)
	attempt.resolved_workflow_json = json.dumps(workflow, indent=2, ensure_ascii=False)
	attempt.resolved_workflow_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
	# Generation Attempt is an internal technical record. Campaign-authorized
	# orchestration must be able to snapshot the resolved workflow even though
	# customer roles do not have direct technical DocType write permission.
	attempt.save(ignore_permissions=True)
	return workflow


def validate_workflow_bindings(workflow_version):
	try:
		workflow = json.loads(workflow_version.workflow_json)
	except json.JSONDecodeError as exc:
		frappe.throw(_("Invalid Workflow JSON: {0}").format(str(exc)))

	if not isinstance(workflow, dict):
		frappe.throw(_("Workflow JSON must define a JSON object."))

	_validate_workflow_bindings(workflow_version, workflow)


def validate_workflow_for_execution(workflow_version, workflow=None):
	"""Validate the ComfyUI API prompt shape before a run can be submitted."""
	if workflow is None:
		try:
			workflow = json.loads(workflow_version.workflow_json)
		except json.JSONDecodeError as exc:
			frappe.throw(
				_("Invalid Workflow JSON for {0}: {1}").format(
					workflow_version.name, str(exc)
				)
			)

	if not isinstance(workflow, dict) or not workflow:
		frappe.throw(
			_("Workflow {0} must contain a non-empty ComfyUI API prompt object.").format(
				workflow_version.name
			)
		)

	invalid_nodes = []
	for node_key, node in workflow.items():
		if not isinstance(node, dict):
			invalid_nodes.append(f"{node_key} (not an object)")
			continue
		class_type = node.get("class_type")
		if not isinstance(class_type, str) or not class_type.strip():
			invalid_nodes.append(str(node_key))

	if invalid_nodes:
		frappe.throw(
			_(
				"Workflow {0} cannot be submitted to ComfyUI. "
				"Node(s) {1} are missing class_type. "
				"Import a ComfyUI API-format workflow JSON before generating."
			).format(workflow_version.name, ", ".join(invalid_nodes))
		)

	_validate_node_references(workflow)

	video_combine_errors = []
	video_combine_required_inputs = {
		"images",
		"frame_rate",
		"loop_count",
		"filename_prefix",
		"format",
		"save_output",
		"pingpong",
	}
	for node_key, node in workflow.items():
		if not isinstance(node, dict) or node.get("class_type") != "VHS_VideoCombine":
			continue
		inputs = node.get("inputs")
		missing_inputs = sorted(video_combine_required_inputs - set(inputs or {}))
		if missing_inputs:
			video_combine_errors.append(
				f"{node_key} (VHS_VideoCombine missing inputs: {', '.join(missing_inputs)})"
			)

	if video_combine_errors:
		frappe.throw(
			_(
				"Workflow {0} cannot be submitted to ComfyUI. "
				"The VHS_VideoCombine node definition is incomplete: {1}. "
				"Export the workflow from ComfyUI in API format and store the complete node inputs."
			).format(workflow_version.name, "; ".join(video_combine_errors))
		)

	return workflow


def _validate_node_references(workflow):
	missing_references = []
	for node_key, node in workflow.items():
		if not isinstance(node, dict):
			continue
		for input_name, value in (node.get("inputs") or {}).items():
			if (
				isinstance(value, list)
				and len(value) == 2
				and isinstance(value[0], (str, int))
				and isinstance(value[1], int)
			):
				source_node = str(value[0])
				if source_node not in workflow:
					missing_references.append(f"{node_key}.{input_name} -> {source_node}")

	if missing_references:
		frappe.throw(
			_("Workflow contains references to missing nodes: {0}").format(
				", ".join(missing_references)
			)
		)


def _validate_workflow_bindings(workflow_version, workflow):
	for binding in workflow_version.bindings:
		if binding.binding_key not in SEMANTIC_BINDING_KEYS:
			frappe.throw(
				_("Unsupported semantic Workflow Binding: {0}").format(binding.binding_key)
			)
		if binding.binding_key in {"first_frame", "last_frame"} and not binding.required_input_role:
			frappe.throw(
				_("Workflow Binding {0} requires an Input Role.").format(binding.binding_key)
			)
		node = workflow.get(binding.node_key)
		if node is None or binding.input_name not in node.get("inputs", {}):
			frappe.throw(
				_(
					"Invalid Workflow Binding {0} for Workflow {1}: "
					"node '{2}' or input '{3}' is missing from the workflow JSON."
				).format(
					binding.binding_key,
					workflow_version.name,
					binding.node_key,
					binding.input_name,
				)
			)


def _resolve_semantic_binding(binding, job, staged_inputs):
	if binding.binding_key in {"first_frame", "last_frame"}:
		return _resolve_generation_input(
			job,
			binding.required_input_role,
			staged_inputs,
			required=bool(binding.required),
		)
	if binding.binding_key == "generation_prompt":
		return job.prompt_text
	frappe.throw(_("Unsupported semantic Workflow Binding: {0}").format(binding.binding_key))


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
