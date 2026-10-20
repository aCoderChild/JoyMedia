"""Native R2V with original role-separated pictures; no generated frame-zero guide.

Uses the installed ComfyUI MiniMaxH3ReferenceToVideo node and the same pinned
Ref2VA checkpoint as register_ref2va_pipeline. No new inference code or weights.
"""

import json

import frappe

from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS, _pipeline_with
from joymedia.patches.register_ref2va_pipeline import execution_spec as anchored_spec

ROLES = ("character", "person", "product", "environment", "general")
WORKFLOW_KEY = "minimax_h3_reference_only"


def specification():
	spec = anchored_spec()
	spec["capabilities"] = ["reference_only", "reference_image", "multi_reference", "native_audio"]
	spec["input_preprocessing"] = {}
	spec["prompt_transforms"] = []
	spec["conditional_inputs"] = [
		{
			"role": role,
			"target": {"node_key": "104", "input_name": f"ref_images.ref_image_{i}"},
			"when_present": ["ref_" + role, 0],
			"when_absent": None,
		}
		for i, role in enumerate(ROLES)
	]
	spec["delivery"] = {
		"width": 1440,
		"height": 2560,
		"fps": 24,
		"audio_sample_rate": 44100,
		"audio_channels": 2,
		"crf": 14,
		"preset": "slow",
		"sharpen": 0.5,
		"contrast": 1.02,
		"brightness": 0,
		"saturation": 1.02,
	}
	return spec


def execute(keyframe_workflow=None):
	if not keyframe_workflow:
		from joymedia.services.workflows.pipeline import get_active_generation_pipeline

		keyframe_workflow = get_active_generation_pipeline().steps[0].workflow
	graph = json.loads((GRAPHS / "minimax_h3_reference_only.json").read_text())
	spec = specification()
	bindings = [
		{
			"binding_key": "generation_prompt",
			"node_key": "104",
			"input_name": "prompt",
			"value_type": "Text",
			"required": 1,
		}
	]
	bindings += [
		{
			"binding_key": role,
			"node_key": "ref_" + role,
			"input_name": "image",
			"required_input_role": role,
			"value_type": "File Path",
			"required": 0,
			"accepted_media_type": "Image",
			"allow_multiple": 0,
		}
		for role in ROLES
	]
	video = None
	for name in frappe.get_all(
		"Generation Workflow",
		filters={"workflow_key": WORKFLOW_KEY},
		pluck="name",
		order_by="version_number desc",
	):
		doc = frappe.get_doc("Generation Workflow", name)
		actual = [{key: r.get(key) for key in b} for r, b in zip(doc.bindings, bindings, strict=False)]
		if (
			len(doc.bindings) == len(bindings)
			and actual == bindings
			and json.loads(doc.workflow_json) == graph
			and json.loads(doc.execution_spec) == spec
		):
			video = name
			break
	if not video:
		video = (
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
	pipeline = _pipeline_with(keyframe_workflow, video)
	if not pipeline:
		pipeline = (
			frappe.get_doc(
				{
					"doctype": "Generation Pipeline",
					"pipeline_key": "original_reference_video",
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
	return {"workflow": video, "pipeline": pipeline, "keyframe_workflow": keyframe_workflow}
