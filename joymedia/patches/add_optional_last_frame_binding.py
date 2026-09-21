import frappe


def execute():
	workflow_profile = frappe.db.get_value(
		"Workflow Profile",
		{"workflow_code": "MINIMAX-H3", "status": "Active"},
		"name",
	)
	if not workflow_profile:
		return

	workflow_version_name = frappe.db.get_value(
		"Workflow Version",
		{"workflow_profile": workflow_profile, "status": ["in", ["Draft", "Testing", "Production"]]},
		"name",
		order_by="version_number desc",
	)
	if not workflow_version_name:
		return

	workflow_version = frappe.get_doc("Workflow Version", workflow_version_name)
	workflow = frappe.parse_json(workflow_version.workflow_json)
	minimax_conditioning = workflow.get("minimax_cond")
	if not isinstance(minimax_conditioning, dict):
		return

	inputs = minimax_conditioning.get("inputs")
	if not isinstance(inputs, dict):
		return

	if "last_frame" not in inputs:
		inputs["last_frame"] = None
		workflow_version.workflow_json = frappe.as_json(workflow)

	if not any(binding.binding_key == "last_frame" for binding in workflow_version.bindings):
		workflow_version.append(
			"bindings",
			{
				"binding_key": "last_frame",
				"node_key": "minimax_cond",
				"input_name": "last_frame",
				"value_source": "Generation Input",
				"required_input_role": "Last Frame",
				"value_type": "File Path",
				"required": 0,
				"allow_override": 0,
				"description": "Optional continuation frame; omitted for first-frame-only generation.",
			},
		)

	if workflow_version.has_value_changed("workflow_json") or any(
		binding.binding_key == "last_frame" for binding in workflow_version.bindings
	):
		workflow_version.save(ignore_permissions=True)
