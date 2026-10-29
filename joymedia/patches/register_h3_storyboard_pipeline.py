"""Opt-in H3 reference composition -> sampled opening still -> H3 animation.

Registration never promotes a global pipeline or rewrites an existing version.
"""

import copy
import json

import frappe

WORKFLOW_KEY = "minimax_h3_storyboard_hold"


def image_recipe(graph, spec, environment_workflow):
	graph, spec = copy.deepcopy(graph), copy.deepcopy(spec)
	graph["111"]["inputs"]["value"] = 73 / 24
	graph["storyboard_frame"] = {
		"class_type": "ImageFromBatch",
		"inputs": {"image": ["10", 0], "batch_index": 68, "length": 1},
	}
	graph["storyboard_save"] = {
		"class_type": "SaveImage",
		"inputs": {"images": ["storyboard_frame", 0], "filename_prefix": "joymedia/storyboard"},
	}
	spec["outputs"] = {
		"primary": {"node_key": "storyboard_save", "media_type": "Image"},
		"preparation_bridge": {"node_key": "92", "frame_index": 68},
	}
	spec["metadata"] = {"frame_count": 1, "output_fps": 24, "produces_video": 0, "produces_audio": 0}
	spec["limits"] = {"max_frames": 1}
	spec["capabilities"] = ["reference_image", "multi_reference", "storyboard_hold"]
	spec["reference_defaults"] = {"Product": "source_pixels"}
	spec["environment_workflow"] = environment_workflow
	spec["parameters"] = [
		p for p in spec["parameters"] if p["semantic"] not in {"frame_count", "output_prefix"}
	]
	spec["parameters"] += [
		{"semantic": "output_prefix", "node_key": node, "input_name": "filename_prefix"}
		for node in ("92", "storyboard_save")
	]
	return graph, spec


def execute(reference_workflow=None, environment_workflow=None):
	from joymedia.patches.register_h3_standard_pipeline import execute as register_pipeline
	from joymedia.services.workflows.pipeline import get_active_generation_pipeline, get_pipeline_steps

	if not reference_workflow:
		rows = frappe.get_all(
			"Generation Workflow",
			filters={"workflow_key": ["like", "minimax_h3_reference_only%"]},
			pluck="name",
			order_by="creation desc",
			limit=1,
		)
		reference_workflow = rows[0] if rows else None
	if not reference_workflow:
		raise ValueError(
			"Register a reference-only H3 workflow before installing its storyboard image stage."
		)
	base = frappe.get_doc("Generation Workflow", reference_workflow)
	if not environment_workflow:
		environment_workflow = get_pipeline_steps(get_active_generation_pipeline().name)[0].workflow
		environment = frappe.get_doc("Generation Workflow", environment_workflow)
		environment_workflow = (frappe.parse_json(environment.execution_spec or "{}") or {}).get(
			"environment_workflow"
		) or environment_workflow
	if frappe.db.get_value("Generation Workflow", environment_workflow, "output_media_type") != "Image":
		raise ValueError("Choose an independent image workflow for empty environments.")
	graph, spec = image_recipe(
		frappe.parse_json(base.workflow_json), frappe.parse_json(base.execution_spec), environment_workflow
	)
	for name in frappe.get_all(
		"Generation Workflow", filters={"workflow_key": WORKFLOW_KEY}, pluck="name", order_by="creation desc"
	):
		stored = frappe.get_doc("Generation Workflow", name)
		if (
			frappe.parse_json(stored.workflow_json) == graph
			and frappe.parse_json(stored.execution_spec) == spec
		):
			return {"storyboard_workflow": name, **register_pipeline(keyframe_workflow=name)}
	doc = frappe.copy_doc(base)
	doc.workflow_key = WORKFLOW_KEY
	doc.workflow_json = json.dumps(graph)
	doc.execution_spec = json.dumps(spec)
	name = doc.insert(ignore_permissions=True).name
	return {"storyboard_workflow": name, **register_pipeline(keyframe_workflow=name)}
