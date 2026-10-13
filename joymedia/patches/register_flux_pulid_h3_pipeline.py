"""Opt-in install script (not run by migrate): register the FLUX + PuLID Face Lock keyframe workflow and the FLUX -> H3 pipeline.

The graph is ComfyUI-PuLID-Flux-Enhanced's shipped ``pulid_flux_16bit_simple``
template converted to API format (installed model names; PreviewImage replaced
by SaveImage). The H3 stage is the shipped "Image to Video (MiniMax H3)" subgraph flattened
into an API graph (the earlier ``minimax_h3_tung`` record holds an unexecutable
UI-format export). Registration does not promote the pipeline.
"""

import json
from pathlib import Path

import frappe

WORKFLOW_KEY = "flux_pulid_keyframe"
PIPELINE_KEY = "flux_pulid_h3_i2v"
H3_WORKFLOW_KEY = "minimax_h3_i2v"
GRAPHS = Path(__file__).resolve().parent.parent / "workflow_adapters" / "graphs"
GRAPH = GRAPHS / "flux_pulid_keyframe.json"


def execute():
	h3 = _register_h3()
	if not h3:
		return
	flux = frappe.db.get_value("Generation Workflow", {"workflow_key": WORKFLOW_KEY}, "name")
	if not flux:
		spec = {
			"parameters": [
				{"semantic": "seed", "node_key": "25", "input_name": "noise_seed"},
				{"semantic": "width", "node_key": "27", "input_name": "width"},
				{"semantic": "height", "node_key": "27", "input_name": "height"},
				{"semantic": "output_prefix", "node_key": "50", "input_name": "filename_prefix"},
			],
			"outputs": {"primary": {"node_key": "50", "media_type": "Image"}},
			"metadata": {"frame_count": 1, "produces_video": 0, "produces_audio": 0},
		}
		doc = frappe.get_doc({
			"doctype": "Generation Workflow",
			"workflow_key": WORKFLOW_KEY,
			"adapter_key": "comfyui_generic",
			"workflow_json": GRAPH.read_text(),
			"execution_spec": json.dumps(spec),
		})
		doc.append("bindings", {
			"binding_key": "generation_prompt", "node_key": "6", "input_name": "text",
			"value_type": "Text", "required": 1,
		})
		doc.append("bindings", {
			"binding_key": "face_reference", "node_key": "54", "input_name": "image",
			"required_input_role": "person", "value_type": "File Path", "required": 1,
			"accepted_media_type": "Image", "allow_multiple": 0,
		})
		doc.insert(ignore_permissions=True)
		flux = doc.name
	if not frappe.db.exists("Generation Pipeline Step", {"parenttype": "Generation Pipeline", "workflow": h3}):
		frappe.get_doc({
			"doctype": "Generation Pipeline",
			"pipeline_key": PIPELINE_KEY,
			"output_media_type": "Video",
			"steps": [
				{"step_key": "keyframe", "workflow": flux, "prompt_source": "Image", "produces_artifact_role": "Primary Image"},
				{
					"step_key": "video", "workflow": h3, "prompt_source": "Motion", "depends_on_step": "keyframe",
					"consumes_artifact_role": "Primary Image", "produces_artifact_role": "Primary Video",
				},
			],
		}).insert(ignore_permissions=True)


def _register_h3():
	"""Latest H3 workflow, creating a version that can continue a shot from its last frame."""
	name = frappe.db.get_value(
		"Generation Workflow", {"workflow_key": H3_WORKFLOW_KEY}, "name", order_by="version_number desc"
	)
	if name and frappe.db.get_value("Generation Workflow", name, "continuation_workflow"):
		return name
	continuation = frappe.db.get_value(
		"Generation Workflow", {"workflow_key": H3_WORKFLOW_KEY + "_continuation"}, "name"
	) or _insert_h3(H3_WORKFLOW_KEY + "_continuation")
	return _insert_h3(H3_WORKFLOW_KEY, continuation)


def _insert_h3(workflow_key, continuation=None):
	spec = {
		"parameters": [
			{"semantic": "seed", "node_key": "15", "input_name": "noise_seed"},
			{"semantic": "width", "node_key": "104", "input_name": "width"},
			{"semantic": "height", "node_key": "104", "input_name": "height"},
			{"semantic": "frame_count", "node_key": "111", "input_name": "value", "transform": "frames_to_seconds", "fps": 24},
			{"semantic": "output_prefix", "node_key": "92", "input_name": "filename_prefix"},
		],
		"outputs": {"primary": {"node_key": "92", "media_type": "Video"}},
		"metadata": {"frame_count": 121, "output_fps": 24, "produces_video": 1, "produces_audio": 1},
	}
	doc = frappe.get_doc({
		"doctype": "Generation Workflow",
		"workflow_key": workflow_key,
		"adapter_key": "comfyui_generic",
		"continuation_workflow": continuation,
		"workflow_json": (GRAPHS / "minimax_h3_i2v.json").read_text(),
		"execution_spec": json.dumps(spec),
	})
	doc.append("bindings", {
		"binding_key": "generation_prompt", "node_key": "104", "input_name": "prompt",
		"value_type": "Text", "required": 1,
	})
	doc.append("bindings", {
		"binding_key": "first_frame", "node_key": "114", "input_name": "image",
		"required_input_role": "first_frame", "value_type": "File Path", "required": 1,
		"accepted_media_type": "Image", "allow_multiple": 0,
	})
	doc.insert(ignore_permissions=True)
	return doc.name
