"""Inspect executable workflow revisions, never equate a checkout with a model."""

import json

import frappe

from joymedia.services.workflows.capabilities import controls
from joymedia.services.workflows.schema import graph_schema_errors


@frappe.whitelist()
def workflow_inventory(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	from joymedia.services.workflows.comfyui import get_object_info

	metadata = get_object_info()
	items = []
	for version in frappe.get_all(
		"Generation Workflow",
		fields=["name", "workflow_key", "version_number", "workflow_json", "execution_spec"],
		order_by="workflow_key asc, version_number desc",
	):
		try:
			graph = json.loads(version.workflow_json)
			bound = frappe.get_all(
				"Workflow Binding",
				filters={"parent": version.name, "parenttype": "Generation Workflow"},
				fields=["node_key", "input_name"],
			)
			errors = graph_schema_errors(
				graph, metadata, bound_inputs={(str(b.node_key), b.input_name) for b in bound}
			)
			capabilities = sorted(controls(version))
		except (ValueError, TypeError) as exc:
			errors, capabilities = [str(exc)], []
		items.append(
			{
				"workflow": version.name,
				"key": version.workflow_key,
				"revision": version.version_number,
				"capabilities": capabilities,
				"available": not errors,
				"problems": errors[:20],
			}
		)
	return {"workflows": items, "registered_node_count": len(metadata)}
