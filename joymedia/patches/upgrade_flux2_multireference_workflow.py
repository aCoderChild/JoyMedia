"""Install a versioned Flux 2 multi-reference keyframe workflow.

The original workflow has person/product/environment slots.  This revision adds
an explicit second product and an unlimited overflow collection that is
deterministically composed into one reference board before reaching ComfyUI.
"""

from __future__ import annotations

import copy

import frappe

WORKFLOW_KEY = "flux2_klein_multireference_keyframe"
PIPELINE_KEY = "flux2_h3_i2v_candidate"


def execute():
	if _installed_workflow():
		return
	base = _workflow_version(WORKFLOW_KEY, 1)
	if not base:
		return
	graph = frappe.parse_json(base.workflow_json)
	spec = frappe.parse_json(base.execution_spec)
	_add_reference_branch(graph, spec, "product", "product_2")
	_add_reference_branch(graph, spec, "product", "reference_board")
	preprocessing = spec.setdefault("input_preprocessing", {})
	preprocessing["compose_image_roles"] = sorted(
		set(preprocessing.get("compose_image_roles") or []) | {"reference_board"}
	)

	workflow = frappe.get_doc(
		{
			"doctype": "Generation Workflow",
			"workflow_key": WORKFLOW_KEY,
			"adapter_key": base.adapter_key,
			"continuation_workflow": base.continuation_workflow,
			"workflow_json": frappe.as_json(graph),
			"execution_spec": frappe.as_json(spec),
		}
	)
	for binding in base.bindings:
		workflow.append(
			"bindings",
			{
				"binding_key": binding.binding_key,
				"node_key": binding.node_key,
				"input_name": binding.input_name,
				"required_input_role": binding.required_input_role,
				"value_type": binding.value_type,
				"required": binding.required,
				"accepted_media_type": binding.accepted_media_type or "Any",
				"allow_multiple": binding.allow_multiple,
			},
		)
	workflow.append(
		"bindings",
		{
			"binding_key": "product_2_reference",
			"node_key": "product_2_image",
			"input_name": "image",
			"required_input_role": "product_2",
			"value_type": "File Paths",
			"required": 0,
			"accepted_media_type": "Image",
			"allow_multiple": 0,
		},
	)
	workflow.append(
		"bindings",
		{
			"binding_key": "reference_board",
			"node_key": "reference_board_image",
			"input_name": "image",
			"required_input_role": "reference_board",
			"value_type": "File Paths",
			"required": 0,
			"accepted_media_type": "Image",
			"allow_multiple": 1,
		},
	)
	workflow.insert(ignore_permissions=True)
	_create_pipeline(workflow.name)


def _installed_workflow():
	for row in frappe.get_all("Generation Workflow", filters={"workflow_key": WORKFLOW_KEY}, pluck="name"):
		roles = set(frappe.get_all("Workflow Binding", filters={"parent": row}, pluck="required_input_role"))
		if {"product_2", "reference_board"}.issubset(roles):
			return True
	return False


def _add_reference_branch(graph, spec, source_prefix, target_prefix):
	"""Clone a ReferenceLatent branch and let the generic adapter rewire it."""
	keys = ("image", "scale", "encode", "positive", "negative")
	for suffix in keys:
		source_key = f"{source_prefix}_{suffix}"
		target_key = f"{target_prefix}_{suffix}"
		node = copy.deepcopy(graph[source_key])
		if suffix == "image":
			node["inputs"]["image"] = f"{target_prefix}_reference"
		elif suffix == "scale":
			node["inputs"]["image"] = [f"{target_prefix}_image", 0]
		elif suffix == "encode":
			node["inputs"]["pixels"] = [f"{target_prefix}_scale", 0]
		elif suffix in {"positive", "negative"}:
			node["inputs"]["latent"] = [f"{target_prefix}_encode", 0]
		graph[target_key] = node
	branches = spec.setdefault("input_preprocessing", {}).setdefault("optional_reference_branches", [])
	branches.append(
		{
			"role": target_prefix,
			"branch_nodes": [f"{target_prefix}_{suffix}" for suffix in keys],
			"image_node": f"{target_prefix}_image",
			"scale_node": f"{target_prefix}_scale",
			"encode_node": f"{target_prefix}_encode",
			"positive_node": f"{target_prefix}_positive",
			"negative_node": f"{target_prefix}_negative",
		}
	)


def _create_pipeline(keyframe_workflow):
	base = _pipeline_version(PIPELINE_KEY, 1)
	if not base:
		return
	video_step = next(step for step in base.steps if step.step_key == "video")
	pipeline = frappe.get_doc(
		{
			"doctype": "Generation Pipeline",
			"pipeline_key": PIPELINE_KEY,
			"steps": [
				{
					"step_key": "keyframe",
					"workflow": keyframe_workflow,
					"prompt_source": "Image",
					"produces_artifact_role": "Primary Image",
				},
				{
					"step_key": "video",
					"workflow": video_step.workflow,
					"prompt_source": video_step.prompt_source or "Motion",
					"depends_on_step": "keyframe",
					"consumes_artifact_role": "Primary Image",
					"produces_artifact_role": video_step.produces_artifact_role,
				},
			],
		}
	)
	pipeline.insert(ignore_permissions=True)


def _workflow_version(workflow_key, version_number):
	name = frappe.db.get_value(
		"Generation Workflow", {"workflow_key": workflow_key, "version_number": version_number}, "name"
	)
	if not name:
		# Some minimal installations do not ship the optional candidate workflow.
		# A migration must remain safe there; the router simply never selects it.
		return None
	return frappe.get_doc("Generation Workflow", name)


def _pipeline_version(pipeline_key, version_number):
	name = frappe.db.get_value(
		"Generation Pipeline", {"pipeline_key": pipeline_key, "version_number": version_number}, "name"
	)
	if not name:
		return None
	return frappe.get_doc("Generation Pipeline", name)
