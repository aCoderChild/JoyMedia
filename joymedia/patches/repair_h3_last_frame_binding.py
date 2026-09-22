import frappe


def execute():
	workflow_versions = frappe.get_all(
		"Workflow",
		filters={"status": ["in", ["Draft", "Testing"]]},
		fields=["name", "workflow_code", "workflow_json"],
	)

	for row in workflow_versions:
		if "h3" not in (row.workflow_code or "").lower():
			continue

		workflow = frappe.parse_json(row.workflow_json)
		conditioning = workflow.get("minimax_cond") or {}
		last_frame_ref = (conditioning.get("inputs") or {}).get("last_frame")
		loader = _find_image_loader(workflow, last_frame_ref)
		if not loader:
			continue

		binding_name = frappe.db.get_value(
			"Workflow Binding",
			{"parent": row.name, "binding_key": "last_frame"},
			"name",
		)
		if binding_name:
			frappe.db.set_value(
				"Workflow Binding",
				binding_name,
				{
					"node_key": loader[0],
					"input_name": loader[1],
					"required": 0,
				},
				update_modified=False,
			)


def _find_image_loader(workflow, reference):
	if not isinstance(reference, list) or not reference:
		return None

	node_key = str(reference[0])
	visited = set()
	while node_key not in visited:
		visited.add(node_key)
		node = workflow.get(node_key) or {}
		inputs = node.get("inputs") or {}
		image_value = inputs.get("image")
		if not isinstance(image_value, list):
			if "image" in inputs:
				return node_key, "image"
			return None

		node_key = str(image_value[0])
	return None
