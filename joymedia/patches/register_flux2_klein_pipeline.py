"""Opt-in install script (not run by migrate): register the FLUX.2 [klein] 4B keyframe workflow and a klein -> H3 pipeline.

FLUX.1-dev with Redux reproduced the reference pictures (a seated mascot holding a paper roll, the room picture's
layout) and ignored the scene's action. FLUX.2 [klein] reads every reference picture as an image to follow
(`ReferenceLatent`) and draws what the prompt says with them. Tested on Demo 1 with each mascot's picture and the
room's close view as separate references and an action-first prompt, it drew the spilled juice, the sheet laid on the
puddle and the sheet held to the cub's cheek, keeping the mascots' design and the room. Each cast member is therefore
its own reference (three slots), not one board. The graph uses only ComfyUI's native FLUX.2 nodes and the models
already on the server. The H3 video stage is the same registered workflow as before.
Registration does not promote the pipeline (`joymedia_active_generation_pipeline`).
"""

import json

import frappe

from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS, _pipeline_with, _register_h3

WORKFLOW_KEY = "flux2_klein_keyframe"
PIPELINE_KEY = "flux2_klein_h3_i2v"
GRAPH = GRAPHS / "flux2_klein_keyframe.json"
# The reference pictures in order: each cast member on its own (a board of several reads as one picture), a real
# person, the product, then the place. (role, slot, node prefix)
SLOTS = (
	("character", 0, "character1"),
	("character", 1, "character2"),
	("character", 2, "character3"),
	("person", 0, "person"),
	("product", 0, "product"),
	("environment", 0, "environment"),
	("general", 0, "general"),
)
ROLES = ("character", "person", "product", "environment", "general")


def execute():
	h3 = _register_h3()
	if not h3:
		return None
	klein = _register_keyframe()
	pipeline = _pipeline_with(klein, h3)
	if not pipeline:
		pipeline = (
			frappe.get_doc(
				{
					"doctype": "Generation Pipeline",
					"pipeline_key": PIPELINE_KEY,
					"output_media_type": "Video",
					"steps": [
						{
							"step_key": "keyframe",
							"workflow": klein,
							"prompt_source": "Image",
							"produces_artifact_role": "Primary Image",
						},
						{
							"step_key": "video",
							"workflow": h3,
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
	return pipeline


def keyframe_spec():
	return {
		"capabilities": ["reference_image", "multi_reference"],
		"parameters": [
			{"semantic": "seed", "node_key": "noise", "input_name": "noise_seed"},
			{
				"semantic": "width",
				"node_key": "latent",
				"input_name": "width",
				"transform": "round_to_multiple",
				"multiple": 16,
			},
			{
				"semantic": "height",
				"node_key": "latent",
				"input_name": "height",
				"transform": "round_to_multiple",
				"multiple": 16,
			},
			{
				"semantic": "width",
				"node_key": "sigmas",
				"input_name": "width",
				"transform": "round_to_multiple",
				"multiple": 16,
			},
			{
				"semantic": "height",
				"node_key": "sigmas",
				"input_name": "height",
				"transform": "round_to_multiple",
				"multiple": 16,
			},
			{"semantic": "output_prefix", "node_key": "save", "input_name": "filename_prefix"},
		],
		"outputs": {"primary": {"node_key": "save", "media_type": "Image"}},
		"metadata": {"frame_count": 1, "produces_video": 0, "produces_audio": 0},
		"input_preprocessing": {
			"optional_input_chains": [
				{
					# Each reference picture present is added to the prompt's conditioning; absent ones leave no nodes.
					"target": {"node_key": "guider", "input_name": "conditioning"},
					"base": ["text", 0],
					"links": [
						{
							"role": role,
							"slot": slot,
							"nodes": [f"{name}_image", f"{name}_scale", f"{name}_encode", f"{name}_ref"],
							"node": f"{name}_ref",
							"input": "conditioning",
						}
						for role, slot, name in SLOTS
					],
				}
			]
		},
	}


def _register_keyframe(*, graph=GRAPH, spec=None, workflow_key=WORKFLOW_KEY, extra_bindings=()):
	"""The latest klein keyframe workflow whose graph and specification are exactly the shipped ones, else a new version."""
	name = frappe.db.get_value(
		"Generation Workflow", {"workflow_key": workflow_key}, "name", order_by="version_number desc"
	)
	spec = keyframe_spec() if spec is None else spec
	if name:
		stored = frappe.db.get_value(
			"Generation Workflow", name, ["execution_spec", "workflow_json"], as_dict=True
		)
		if (
			json.loads(stored.workflow_json) == json.loads(graph.read_text())
			and json.loads(stored.execution_spec) == spec
		):
			return name
	doc = frappe.get_doc(
		{
			"doctype": "Generation Workflow",
			"workflow_key": workflow_key,
			"adapter_key": "comfyui_generic",
			"workflow_json": graph.read_text(),
			"execution_spec": json.dumps(spec),
		}
	)
	doc.append(
		"bindings",
		{
			"binding_key": "generation_prompt",
			"node_key": "text",
			"input_name": "text",
			"value_type": "Text",
			"required": 1,
		},
	)
	for role, _slot, name in SLOTS:
		# Bindings of one role are filled in their order (resolver role slots): the first character, the second…
		doc.append(
			"bindings",
			{
				"binding_key": f"{name}_reference",
				"node_key": f"{name}_image",
				"input_name": "image",
				"required_input_role": role,
				"value_type": "File Path",
				"required": 0,
				"accepted_media_type": "Image",
				"allow_multiple": 0,
			},
		)
	for binding in extra_bindings:
		doc.append("bindings", dict(binding))
	doc.insert(ignore_permissions=True)
	return doc.name
