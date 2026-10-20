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
	flux = _register_keyframe()
	if not _pipeline_with(flux, h3):
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


def _pipeline_with(keyframe_workflow, video_workflow):
	"""A pipeline whose steps are exactly these two workflows, if one is registered."""
	for name in frappe.get_all("Generation Pipeline", pluck="name"):
		if set(frappe.get_all("Generation Pipeline Step", filters={"parent": name}, pluck="workflow")) == {
			keyframe_workflow, video_workflow,
		}:
			return name
	return None


def _current_version(workflow_key):
	"""Latest version of a workflow whose graph is exactly the shipped H3 graph, else None."""
	name = frappe.db.get_value("Generation Workflow", {"workflow_key": workflow_key}, "name", order_by="version_number desc")
	if not name:
		return None
	stored = frappe.db.get_value("Generation Workflow", name, ["workflow_json", "execution_spec"], as_dict=True)
	if json.loads(stored.workflow_json) == json.loads((GRAPHS / "minimax_h3_i2v.json").read_text()) and json.loads(
		stored.execution_spec
	) == _h3_spec():
		return name
	return None


def _register_h3():
	"""Latest H3 workflow with the shipped graph and specification, creating a version when it differs."""
	name = _current_version(H3_WORKFLOW_KEY)
	if name and frappe.db.get_value("Generation Workflow", name, "continuation_workflow"):
		return name
	continuation = _current_version(H3_WORKFLOW_KEY + "_continuation") or _insert_h3(H3_WORKFLOW_KEY + "_continuation")
	return _insert_h3(H3_WORKFLOW_KEY, continuation)


def _h3_spec():
	sizes = [{"width": 1344, "height": 768}, {"width": 768, "height": 1344}, {"width": 1024, "height": 1024}]
	return {
		"capabilities": ["first_frame", "last_frame", "native_audio"],
		"limits": {"max_frames": 124},
		"parameters": [
			{"semantic": "seed", "node_key": "15", "input_name": "noise_seed"},
			# H3's latent grid needs sizes divisible by 32 (the shipped workflow's Resolution Selector rounds to
			# a multiple of 32 for the same reason); 720 is not, and fails inside the sampler.
			{"semantic": "width", "node_key": "104", "input_name": "width", "transform": "nearest_size_dimension", "dimension": "width", "options": sizes},
			{"semantic": "height", "node_key": "104", "input_name": "height", "transform": "nearest_size_dimension", "dimension": "height", "options": sizes},
			{"semantic": "frame_count", "node_key": "111", "input_name": "value", "transform": "frames_to_seconds", "fps": 24},
			{"semantic": "output_prefix", "node_key": "92", "input_name": "filename_prefix"},
		],
		"outputs": {"primary": {"node_key": "92", "media_type": "Video"}},
		# H3's own optional last_frame input: a continuation segment can end on the scene's approved keyframe, which
		# keeps the characters from drifting away from it. Absent, the input stays empty and nothing changes.
		"conditional_inputs": [{
			"role": "last_frame", "target": {"node_key": "104", "input_name": "last_frame"},
			"when_present": ["115", 0], "when_absent": None,
		}],
		"metadata": {"frame_count": 124, "output_fps": 24, "produces_video": 1, "produces_audio": 1},
	}


def _insert_h3(workflow_key, continuation=None):
	spec = _h3_spec()
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
	doc.append("bindings", {
		"binding_key": "last_frame", "node_key": "115", "input_name": "image",
		"required_input_role": "last_frame", "value_type": "File Path", "required": 0,
		"accepted_media_type": "Image", "allow_multiple": 0,
	})
	doc.insert(ignore_permissions=True)
	return doc.name


def _keyframe_spec():
	return {
		"parameters": [
			{"semantic": "seed", "node_key": "25", "input_name": "noise_seed"},
			{"semantic": "width", "node_key": "27", "input_name": "width"},
			{"semantic": "height", "node_key": "27", "input_name": "height"},
			{"semantic": "output_prefix", "node_key": "50", "input_name": "filename_prefix"},
		],
		"outputs": {"primary": {"node_key": "50", "media_type": "Image"}},
		"metadata": {"frame_count": 1, "produces_video": 0, "produces_audio": 0},
		"input_preprocessing": {"optional_input_chains": [
			{   # Human face identity (PuLID) patches the model used by the guider.
				"target": {"node_key": "47", "input_name": "model"}, "base": ["63", 0],
				"links": [{"role": "person", "nodes": ["54", "53", "51", "45", "62"], "node": "62", "input": "model"}],
			},
			{   # Image conditioning (Redux): a mascot or cartoon character (its board), then product and environment
				# references at a gentler strength. A real person is NOT a Redux input: Redux copies a face
				# crop's framing, so a person is identity-locked by PuLID above and the prompt decides the scene.
				"target": {"node_key": "47", "input_name": "conditioning"}, "base": ["26", 0],
				"links": [
					{"role": role, "nodes": [f"{name}_image", f"{name}_encode", f"{name}_redux"],
					 "node": f"{name}_redux", "input": "conditioning"}
					for role, name in (("character", "character"), ("product", "product"), ("environment", "environment"))
				],
			},
		]},
	}


def _register_keyframe():
	"""Keyframe workflow whose character, product and environment references are all optional."""
	name = frappe.db.get_value(
		"Generation Workflow", {"workflow_key": WORKFLOW_KEY}, "name", order_by="version_number desc"
	)
	spec = _keyframe_spec()
	if name:
		stored = frappe.db.get_value("Generation Workflow", name, ["execution_spec", "workflow_json"], as_dict=True)
		# Reuse only a version whose graph and specification are exactly the shipped ones.
		if json.loads(stored.workflow_json) == json.loads(GRAPH.read_text()) and json.loads(stored.execution_spec) == spec:
			return name
	doc = frappe.get_doc({
		"doctype": "Generation Workflow",
		"workflow_key": WORKFLOW_KEY,
		"adapter_key": "comfyui_generic",
		"workflow_json": GRAPH.read_text(),
		"execution_spec": json.dumps(spec),
	})
	doc.append("bindings", {
		"binding_key": "generation_prompt", "node_key": "6", "input_name": "text", "value_type": "Text", "required": 1,
	})
	for binding_key, role, node_key in (
		("person_reference", "person", "54"), ("character_reference", "character", "character_image"),
		("product_reference", "product", "product_image"), ("environment_reference", "environment", "environment_image"),
	):
		doc.append("bindings", {
			"binding_key": binding_key, "node_key": node_key, "input_name": "image",
			"required_input_role": role, "value_type": "File Path", "required": 0,
			"accepted_media_type": "Image", "allow_multiple": 0,
		})
	doc.insert(ignore_permissions=True)
	return doc.name
