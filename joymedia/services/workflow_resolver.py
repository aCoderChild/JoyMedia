import copy
import hashlib
import json

import frappe
from frappe import _

from joymedia.workflow_adapters import get_workflow_adapter
from joymedia.workflow_adapters.base import canonical_workflow_json


_SKIP_BINDING = object()
PROMPT_BINDING_KEY = "generation_prompt"


def get_workflow_input_contract(workflow):
	"""Return the selected workflow's staged-input contract by semantic role."""
	contract = {}
	for binding in workflow.bindings:
		role = frappe.scrub(binding.required_input_role or "")
		if not role:
			continue
		binding_key = frappe.scrub(binding.binding_key or "")
		entry = {
			"role": role,
			"value_type": getattr(binding, "value_type", None) or "File Path",
			"required": bool(binding.required),
			"accepted_media_type": getattr(binding, "accepted_media_type", None) or "Any",
			"allow_multiple": bool(getattr(binding, "allow_multiple", 0))
			or binding_key.startswith("reference_image_"),
		}
		previous = contract.get(role)
		if previous and any(
			previous[field] != entry[field]
			for field in ("value_type", "accepted_media_type", "allow_multiple")
		):
			frappe.throw(_("Workflow bindings for role '{0}' have conflicting input contracts.").format(role))
		if previous:
			previous["required"] = previous["required"] or entry["required"]
		else:
			contract[role] = entry
	return list(contract.values())


def resolve_attempt(attempt_name: str, staged_inputs=None):
	staged_inputs = staged_inputs or {}
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	job = frappe.get_doc("Generation Task", attempt.generation_task)
	run = frappe.get_doc("Generation Run", job.generation_run)
	try:
		run_snapshot = frappe.parse_json(run.project_snapshot_json or "{}")
	except (TypeError, ValueError):
		frappe.throw(_("Generation Run {0} has invalid project snapshot JSON.").format(run.name))
	workflow_version = frappe.get_doc("Generation Workflow", job.workflow)
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

	adapter = get_workflow_adapter(workflow_version)
	width = run_snapshot.get("delivery_width")
	height = run_snapshot.get("delivery_height")
	if not width or not height:
		frappe.throw(_("Generation Run {0} has no valid delivery dimensions in its snapshot.").format(run.name))
	adapter.prepare_execution(
		workflow,
		seed=int(attempt.seed),
		width=int(width),
		height=int(height),
		frame_count=int(job.segment_frame_count),
		output_prefix=f"{job.name}_{attempt.name}",
		last_frame_index=int(job.segment_frame_count) - 1,
		last_frame_prefix=f"{job.name}_{attempt.name}_last_frame",
	)

	if any(
		binding.binding_key == "last_frame" and not staged_inputs.get("last_frame")
		for binding in workflow_version.bindings
	):
		adapter_inputs = {
			role: values[0] if isinstance(values, list) and len(values) == 1 else values
			for role, values in staged_inputs.items()
		}
		adapter.finalize_workflow(workflow, workflow_version, adapter_inputs)

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
	get_workflow_input_contract(workflow_version)
	for binding in workflow_version.bindings:
		binding_key = frappe.scrub(binding.binding_key or "")
		if not binding_key:
			frappe.throw(_("Every Workflow Binding requires a Binding Key."))
		if binding_key != PROMPT_BINDING_KEY and not binding.required_input_role:
			frappe.throw(
				_("Workflow Binding {0} requires an Input Role.").format(binding.binding_key)
			)
		accepted_media_type = getattr(binding, "accepted_media_type", None)
		if accepted_media_type not in (None, "", "Any", "Image", "Video", "Audio"):
			frappe.throw(_("Unsupported Accepted Media Type: {0}").format(accepted_media_type))
		if getattr(binding, "allow_multiple", 0) and getattr(binding, "value_type", None) != "File Paths":
			frappe.throw(_("Workflow Binding {0} must use File Paths when Allow Multiple is enabled.").format(binding.binding_key))
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
	if frappe.scrub(binding.binding_key or "") == PROMPT_BINDING_KEY:
		return job.prompt_text
	if frappe.scrub(binding.binding_key or "").startswith("reference_image_"):
		return _resolve_reference_image_binding(binding, staged_inputs)
	return _resolve_generation_input(
		job,
		binding.required_input_role,
		staged_inputs,
		value_type=binding.value_type,
		required=bool(binding.required),
	)


def _resolve_reference_image_binding(binding, staged_inputs):
	"""Resolve ordered R2V reference_image_1/reference_image_2 bindings."""
	try:
		index = int(str(binding.binding_key).rsplit("_", 1)[1]) - 1
	except (ValueError, IndexError):
		frappe.throw(_("Invalid reference image binding key: {0}").format(binding.binding_key))

	values = staged_inputs.get(frappe.scrub(binding.required_input_role)) or []
	if not isinstance(values, list):
		values = [values]
	if index < len(values) and values[index]:
		return values[index]
	if not binding.required:
		return _SKIP_BINDING
	frappe.throw(
		_("No staged reference image {0} found for Generation Task {1}.").format(
			index + 1, getattr(binding, "generation_task", "") or "the current task"
		)
	)


def _resolve_generation_input(job, required_role, staged_inputs, value_type="File Path", required=True):
	if not required_role:
		frappe.throw(_("Generation Input binding requires Required Input Role."))
	normalized_role = frappe.scrub(required_role)
	staged_value = staged_inputs.get(normalized_role)
	values = staged_value if isinstance(staged_value, list) else ([staged_value] if staged_value else [])
	if values:
		if value_type == "File Paths":
			return values
		if len(values) != 1:
			frappe.throw(
				_("Workflow binding for role '{0}' accepts exactly one input; found {1}.").format(
					normalized_role, len(values)
				)
			)
		return values[0]
	if not required:
		return _SKIP_BINDING
	frappe.throw(
		_("No staged ComfyUI input found for role '{0}' on Generation Task {1}.").format(
			normalized_role, job.name
		)
	)
