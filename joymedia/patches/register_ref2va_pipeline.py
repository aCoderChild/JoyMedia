"""Opt-in Ref2VA + original product conditioning, using native ComfyUI nodes.

Adapted from Comfy-Org/workflow_templates video_minimax_h3_r2v at
59a3b48bf369c5a15f29a1308bae3e279fa15505. Reuses the existing H3 sampler,
AV decode and JoyMedia generic adapter; no model code runs in Frappe.
Registration never promotes the pipeline or rewrites an existing workflow.
"""

import json

import frappe

from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS, _pipeline_with

WORKFLOW_KEY = "minimax_h3_ref2va_product"
GRAPH = GRAPHS / "minimax_h3_ref2va.json"
MODEL = json.loads((GRAPHS / "minimax_h3_ref2va.model.json").read_text())


def execution_spec():
	return json.loads((GRAPHS / "minimax_h3_ref2va.execution.json").read_text())


def register_video():
	graph, spec = json.loads(GRAPH.read_text()), execution_spec()
	bindings = [
		{
			"binding_key": "generation_prompt",
			"node_key": "104",
			"input_name": "prompt",
			"value_type": "Text",
			"required": 1,
		},
		*[
			{
				"binding_key": role,
				"node_key": node,
				"input_name": "image",
				"required_input_role": role,
				"value_type": "File Path",
				"required": required,
				"accepted_media_type": "Image",
				"allow_multiple": 0,
			}
			for role, node, required in [
				("first_frame", "114", 1),
				("last_frame", "115", 0),
				("product", "product", 0),
				("character", "character", 0),
			]
		],
	]
	for name in frappe.get_all(
		"Generation Workflow",
		filters={"workflow_key": WORKFLOW_KEY},
		pluck="name",
		order_by="version_number desc",
	):
		doc = frappe.get_doc("Generation Workflow", name)
		actual = [
			{key: row.get(key) for key in expected}
			for row, expected in zip(doc.bindings, bindings, strict=False)
		]
		if (
			len(doc.bindings) == len(bindings)
			and actual == bindings
			and json.loads(doc.workflow_json) == graph
			and json.loads(doc.execution_spec) == spec
		):
			return name
	return (
		frappe.get_doc(
			{
				"doctype": "Generation Workflow",
				"workflow_key": WORKFLOW_KEY,
				"adapter_key": "comfyui_generic",
				"workflow_json": json.dumps(graph),
				"execution_spec": json.dumps(spec),
				"bindings": bindings,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def execute(keyframe_workflow=None):
	if not keyframe_workflow:
		from joymedia.services.workflows.pipeline import get_active_generation_pipeline, get_pipeline_steps

		steps = get_pipeline_steps(get_active_generation_pipeline().name)
		keyframe_workflow = steps[0].workflow
	if frappe.db.get_value("Generation Workflow", keyframe_workflow, "output_media_type") != "Image":
		raise ValueError("Ref2VA needs an image-producing keyframe stage.")
	video = register_video()
	pipeline = _pipeline_with(keyframe_workflow, video)
	if not pipeline:
		pipeline = (
			frappe.get_doc(
				{
					"doctype": "Generation Pipeline",
					"pipeline_key": "reference_conditioned_product_video",
					"output_media_type": "Video",
					"steps": [
						{
							"step_key": "keyframe",
							"workflow": keyframe_workflow,
							"prompt_source": "Image",
							"produces_artifact_role": "Primary Image",
						},
						{
							"step_key": "video",
							"workflow": video,
							"prompt_source": "Motion",
							"depends_on_step": "keyframe",
							"consumes_artifact_role": "Primary Image",
							"produces_artifact_role": "Primary Video",
						},
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return {"workflow": video, "pipeline": pipeline}
