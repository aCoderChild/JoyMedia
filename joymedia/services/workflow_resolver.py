import copy
import hashlib
import json

import frappe
from frappe import _

from joymedia.workflow_adapters import get_workflow_adapter
from joymedia.workflow_adapters.base import canonical_workflow_json


_SKIP_BINDING = object()
PROMPT_BINDING_KEY = "generation_prompt"


def workflow_supports_continuation(workflow):
	"""Return whether a workflow has a required first-frame input binding."""
	return any(
		frappe.scrub(binding.required_input_role or "") == "first_frame"
		and bool(binding.required)
		for binding in workflow.bindings
	)


def get_workflow_input_contract(workflow):
	"""Return the selected workflow's staged-input contract by semantic role."""
	contract = {}
	for binding in workflow.bindings:
		role = frappe.scrub(binding.required_input_role or "")
		if not role:
			continue
		entry = {
			"role": role,
			"value_type": getattr(binding, "value_type", None) or "File Path",
			"required": bool(binding.required),
			"accepted_media_type": getattr(binding, "accepted_media_type", None) or "Any",
			"allow_multiple": bool(getattr(binding, "allow_multiple", 0)),
			"min_count": 0,
			"max_count": 0,
		}
		if entry["allow_multiple"]:
			# A list-valued binding owns an unbounded ordered input collection.
			entry["max_count"] = 0
		if entry["required"]:
			entry["min_count"] += 1
		if not entry["allow_multiple"]:
			entry["max_count"] += 1
		previous = contract.get(role)
		if previous and any(
			previous[field] != entry[field]
			for field in ("value_type", "accepted_media_type", "allow_multiple")
		):
			frappe.throw(_("Workflow bindings for role '{0}' have conflicting input contracts.").format(role))
		if previous:
			previous["required"] = previous["required"] or entry["required"]
			previous["min_count"] += entry["min_count"]
			previous["max_count"] += entry["max_count"]
		else:
			contract[role] = entry
	return list(contract.values())


def validate_role_input_count(workflow, role, count):
	"""Throw unless `count` inputs fit the slots a workflow provides for one role."""
	entry = next(
		(item for item in get_workflow_input_contract(workflow) if item["role"] == frappe.scrub(role)),
		None,
	)
	if not entry or entry["value_type"] == "File Paths":
		return
	minimum, maximum = entry["min_count"], entry["max_count"]
	if count < minimum or (maximum and count > maximum):
		expected = minimum if minimum == maximum else f"{minimum}-{maximum or 'n'}"
		frappe.throw(
			_("Workflow input role '{0}' expects {1} input(s); found {2}.").format(
				frappe.scrub(role), expected, count
			)
		)


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
	width = run_snapshot.get("delivery_width")
	height = run_snapshot.get("delivery_height")
	fps = run_snapshot.get("output_fps") or workflow_version.output_fps or 24
	if not width or not height:
		frappe.throw(_("Generation Run {0} has no valid delivery dimensions in its snapshot.").format(run.name))
	workflow = build_execution_workflow(
		workflow_version,
		inputs={PROMPT_BINDING_KEY: job.prompt_text, **staged_inputs},
		seed=int(attempt.seed),
		width=int(width),
		height=int(height),
		fps=float(fps),
		frame_count=int(job.segment_frame_count),
		output_prefix=f"{job.name}_{attempt.name}",
		last_frame_index=int(job.segment_frame_count) - 1,
		last_frame_prefix=f"{job.name}_{attempt.name}_last_frame",
	)

	# Provider credentials are injected only into the outbound prompt.  Keep them
	# out of the immutable Attempt snapshot, logs, hashes, and customer-visible
	# diagnostics.
	recorded_workflow = copy.deepcopy(workflow)
	for node in recorded_workflow.values():
		inputs = node.get("inputs") if isinstance(node, dict) else None
		if not isinstance(inputs, dict):
			continue
		for input_name in list(inputs):
			if any(token in str(input_name).lower() for token in ("api_key", "auth_token", "token_comfy_org")):
				inputs[input_name] = "<redacted>"
	canonical = canonical_workflow_json(recorded_workflow)
	attempt.resolved_workflow_json = json.dumps(recorded_workflow, indent=2, ensure_ascii=False)
	attempt.resolved_workflow_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
	# Generation Attempt is an internal technical record. Campaign-authorized
	# orchestration must be able to snapshot the resolved workflow even though
	# customer roles do not have direct technical DocType write permission.
	attempt.save(ignore_permissions=True)
	return workflow


def build_execution_workflow(
	workflow_version,
	*,
	inputs,
	seed,
	width,
	height,
	fps,
	frame_count,
	output_prefix,
	last_frame_index=None,
	last_frame_prefix=None,
):
	"""Build a ComfyUI prompt from a declared workflow contract.

	This is deliberately independent of Generation Attempt.  Normal renders,
	post-production and future services therefore use the exact same binding and
	execution-specification path rather than mutating provider or model node IDs.
	"""
	try:
		base_workflow = json.loads(workflow_version.workflow_json)
	except json.JSONDecodeError as exc:
		frappe.throw(_("Invalid Workflow JSON: {0}").format(str(exc)))
	validate_workflow_for_execution(workflow_version, base_workflow)
	workflow = copy.deepcopy(base_workflow)
	_validate_workflow_bindings(workflow_version, workflow)
	_apply_declared_bindings(workflow_version, workflow, inputs)
	adapter = get_workflow_adapter(workflow_version)
	adapter.prepare_execution(
		workflow,
		seed=int(seed),
		width=int(width),
		height=int(height),
		fps=float(fps),
		frame_count=int(frame_count),
		output_prefix=output_prefix,
		last_frame_index=last_frame_index,
		last_frame_prefix=last_frame_prefix,
	)
	adapter.finalize_workflow(workflow, workflow_version, inputs)
	return workflow


def validate_workflow_bindings(workflow_version):
	try:
		workflow = json.loads(workflow_version.workflow_json)
	except json.JSONDecodeError as exc:
		frappe.throw(_("Invalid Workflow JSON: {0}").format(str(exc)))

	if not isinstance(workflow, dict):
		frappe.throw(_("Workflow JSON must define a JSON object."))

	_validate_workflow_bindings(workflow_version, workflow)
	adapter = get_workflow_adapter(workflow_version)
	validate_specification = getattr(adapter, "validate_specification", None)
	if validate_specification:
		try:
			validate_specification(workflow)
		except (TypeError, ValueError, KeyError) as exc:
			frappe.throw(
				_("Invalid Execution Specification for Workflow {0}: {1}").format(
					workflow_version.name, str(exc)
				)
			)


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


def _apply_declared_bindings(workflow_version, workflow, inputs):
	"""Apply semantic inputs to graph bindings without knowing a model family."""
	for binding in workflow_version.bindings:
		value = _resolve_declared_binding(
			binding,
			inputs,
			role_slot=_role_slot_index(workflow_version.bindings, binding),
		)
		if value is not _SKIP_BINDING:
			workflow[str(binding.node_key)]["inputs"][binding.input_name] = value


def _resolve_declared_binding(binding, inputs, role_slot=0):
	if frappe.scrub(binding.binding_key or "") == PROMPT_BINDING_KEY:
		value = inputs.get(PROMPT_BINDING_KEY)
		if value not in (None, ""):
			return value
		if not binding.required:
			return _SKIP_BINDING
		frappe.throw(_("Workflow requires a generation prompt."))
	return _resolve_input_value(
		binding.required_input_role,
		inputs,
		value_type=binding.value_type,
		required=bool(binding.required),
		allow_multiple=bool(getattr(binding, "allow_multiple", 0)),
		role_slot=role_slot,
	)
def _resolve_semantic_binding(binding, job, staged_inputs, role_slot=0):
	return _resolve_declared_binding(
		binding,
		{PROMPT_BINDING_KEY: job.prompt_text, **staged_inputs},
		role_slot=role_slot,
	)


def _role_slot_index(bindings, binding):
	"""Return a role-local slot index without encoding order in a binding name."""
	role = frappe.scrub(getattr(binding, "required_input_role", None) or "")
	if not role or bool(getattr(binding, "allow_multiple", 0)):
		return 0
	index = 0
	for candidate in bindings:
		if candidate is binding:
			return index
		if (
			frappe.scrub(getattr(candidate, "required_input_role", None) or "") == role
			and not bool(getattr(candidate, "allow_multiple", 0))
			and frappe.scrub(getattr(candidate, "binding_key", "") or "") != PROMPT_BINDING_KEY
		):
			index += 1
	return index


def _resolve_input_value(
	required_role, inputs, value_type="File Path", required=True,
	allow_multiple=False, role_slot=0,
):
	if not required_role:
		frappe.throw(_("Generation Input binding requires Required Input Role."))
	normalized_role = frappe.scrub(required_role)
	staged_value = inputs.get(normalized_role)
	values = staged_value if isinstance(staged_value, list) else ([staged_value] if staged_value else [])
	if values:
		if value_type == "File Paths" and allow_multiple:
			return values
		if role_slot < len(values):
			return values[role_slot]
		if not required:
			return _SKIP_BINDING
		frappe.throw(
			_("Workflow binding for role '{0}' requires input slot {1}; found {2}.").format(
				normalized_role, role_slot + 1, len(values)
			)
		)
	if not required:
		return _SKIP_BINDING
	frappe.throw(_("No workflow input found for role '{0}'.").format(normalized_role))
