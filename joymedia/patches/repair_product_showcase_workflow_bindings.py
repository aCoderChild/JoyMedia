import json

import frappe


def execute():
	"""Create a usable product-showcase workflow from the latest real API graph.

	Older records may contain only node placeholders and no binding rows. They
	must not be selected for new generation runs.
	"""
	rows = frappe.get_all(
		"Workflow",
		filters={"workflow_key": "product_showcase"},
		fields=["name", "workflow_json"],
		order_by="version_number desc, modified desc",
	)

	source = None
	workflow_data = None
	for row in rows:
		try:
			candidate = json.loads(row.workflow_json)
		except (TypeError, ValueError):
			continue
		if not isinstance(candidate, dict) or not _has_class_types(candidate):
			continue
		if not _find_direct_image_loader(candidate, preferred_key="load_img"):
			continue
		source = row
		workflow_data = candidate
		break

	if not source:
		return

	required_binding_exists = frappe.db.exists(
		"Workflow Binding",
		{
			"parent": source.name,
			"parenttype": "Workflow",
			"value_source": "Generation Input",
			"required": 1,
			"required_input_role": ["is", "set"],
		},
	)
	if required_binding_exists:
		return

	first_frame_node = _find_direct_image_loader(workflow_data, preferred_key="load_img")
	if not first_frame_node:
		return

	clone = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_key": "product_showcase",
			"workflow_json": source.workflow_json,
		}
	)
	clone.append(
		"bindings",
		{
			"binding_key": "first_frame",
			"node_key": first_frame_node,
			"input_name": "image",
			"value_source": "Generation Input",
			"required_input_role": "first_frame",
			"value_type": "File Path",
			"required": 1,
			"allow_override": 0,
		},
	)

	last_frame_node = _find_last_frame_loader(workflow_data)
	if last_frame_node:
		clone.append(
			"bindings",
			{
				"binding_key": "last_frame",
				"node_key": last_frame_node,
				"input_name": "image",
				"value_source": "Generation Input",
				"required_input_role": "last_frame",
				"value_type": "File Path",
				"required": 0,
				"allow_override": 0,
			},
		)

	clone.insert(ignore_permissions=True)
	for specification in frappe.get_all(
		"Media Specification",
		filters={"workflow": ["in", [row.name for row in rows]], "status": "Draft"},
		pluck="name",
	):
		frappe.db.set_value(
			"Media Specification", specification, "workflow", clone.name, update_modified=False
		)


def _has_class_types(workflow):
	return bool(workflow) and all(
		isinstance(node, dict) and isinstance(node.get("class_type"), str) and node["class_type"].strip()
		for node in workflow.values()
	)


def _find_direct_image_loader(workflow, preferred_key=None):
	if preferred_key:
		node = workflow.get(preferred_key) or {}
		if "image" in (node.get("inputs") or {}):
			return preferred_key
	for node_key, node in workflow.items():
		inputs = node.get("inputs") or {}
		if "image" in inputs and not isinstance(inputs["image"], list):
			return str(node_key)
	return None


def _find_last_frame_loader(workflow):
	conditioning = workflow.get("minimax_cond") or {}
	reference = (conditioning.get("inputs") or {}).get("last_frame")
	visited = set()
	while isinstance(reference, list) and reference:
		node_key = str(reference[0])
		if node_key in visited:
			return None
		visited.add(node_key)
		node = workflow.get(node_key) or {}
		inputs = node.get("inputs") or {}
		if "image" in inputs and not isinstance(inputs["image"], list):
			return node_key
		reference = inputs.get("image")
	return None
