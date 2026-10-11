import json

import frappe


def execute():
	"""Align declared file cardinality with scalar workflow input placeholders.

	A reusable workflow binding is the source of truth for whether an input node
	receives one path or a collection. Older workflow records accidentally marked
	single filename inputs as multi-file paths, causing ComfyUI to receive a JSON
	array where it expects a filename.
	"""
	for workflow in frappe.get_all("Generation Workflow", fields=["name", "workflow_json"]):
		try:
			graph = json.loads(workflow.workflow_json or "{}")
		except (TypeError, ValueError):
			continue
		for binding in frappe.get_all(
			"Workflow Binding",
			filters={"parent": workflow.name, "parenttype": "Generation Workflow", "value_type": "File Paths", "allow_multiple": 1},
			fields=["name", "node_key", "input_name"],
		):
			node = graph.get(str(binding.node_key)) or {}
			value = (node.get("inputs") or {}).get(binding.input_name)
			if isinstance(value, str):
				frappe.db.set_value("Workflow Binding", binding.name, {
					"value_type": "File Path",
					"allow_multiple": 0,
				}, update_modified=False)
