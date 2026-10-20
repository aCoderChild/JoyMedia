"""Versioned provider recipe for automatic source-reference preparation."""

import json
from pathlib import Path

import frappe


def execute():
	graph = json.loads(
		(Path(__file__).parents[1] / "workflow_adapters/graphs/reference_retention.json").read_text()
	)
	spec = {
		"capabilities": ["reference_image"],
		"outputs": {"primary": {"node_key": "retain", "media_type": "Image"}},
		"metadata": {"frame_count": 1, "output_fps": 1, "produces_video": 0, "produces_audio": 0},
	}
	bindings = [
		dict(
			binding_key=key,
			node_key=node,
			input_name=input,
			required_input_role=role,
			value_type=kind,
			required=1,
			accepted_media_type="Image" if kind == "File Path" else "Any",
		)
		for key, node, input, role, kind in [
			("scene", "scene", "image", "scene", "File Path"),
			("source", "retain", "source_image", "source", "File Path"),
			("recipe", "retain", "recipe_sha256", "recipe", "Text"),
		]
	]
	for name in frappe.get_all(
		"Generation Workflow",
		filters={"workflow_key": "reference_retention"},
		pluck="name",
		order_by="version_number desc",
	):
		doc = frappe.get_doc("Generation Workflow", name)
		if json.loads(doc.workflow_json) == graph and json.loads(doc.execution_spec) == spec:
			return doc.name
	return (
		frappe.get_doc(
			dict(
				doctype="Generation Workflow",
				workflow_key="reference_retention",
				adapter_key="comfyui_generic",
				workflow_json=json.dumps(graph),
				execution_spec=json.dumps(spec),
				bindings=bindings,
			)
		)
		.insert(ignore_permissions=True)
		.name
	)
