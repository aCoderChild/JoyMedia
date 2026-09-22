import frappe


def execute():
	if frappe.db.exists("Workflow", {"workflow_code": "MINIMAX-H3"}):
		return

	old_table = frappe.db.sql("SHOW TABLES LIKE 'tabWorkflow Version'")
	if not old_table:
		return

	old_workflow = frappe.db.sql(
		"""
		SELECT version.name, version.workflow_json, version.version_number,
			version.status, profile.default_workflow_version
		FROM `tabWorkflow Version` version
		LEFT JOIN `tabWorkflow Profile` profile
			ON profile.name = version.workflow_profile
		WHERE profile.workflow_code = 'MINIMAX-H3'
		ORDER BY version.version_number DESC, version.creation DESC
		LIMIT 1
		""",
		as_dict=True,
	)
	if not old_workflow:
		return

	old_workflow = old_workflow[0]
	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_key": "product_showcase",
			"workflow_code": "MINIMAX-H3",
			"version_number": old_workflow.version_number or 1,
			"version_label": "MiniMax H3 v{0}".format(old_workflow.version_number or 1),
			"status": old_workflow.status if old_workflow.status in ("Draft", "Testing", "Production", "Deprecated") else "Draft",
			"is_default": int(
				old_workflow.default_workflow_version == old_workflow.name
				and old_workflow.status in ("Testing", "Production")
			),
			"client_name": "Product Showcase",
			"client_description": "Clean, polished product presentation for launches and ecommerce.",
			"client_visible": 1,
			"is_active": 1,
			"workflow_json": old_workflow.workflow_json,
		}
	)

	for binding in frappe.db.sql(
		"""
		SELECT binding_key, node_key, input_name, value_source,
			required_input_role, value_type, required, allow_override, description
		FROM `tabWorkflow Binding`
		WHERE parent = %s AND parenttype = 'Workflow Version'
		""",
		old_workflow.name,
		as_dict=True,
	):
		workflow.append("bindings", binding)

	workflow.insert(ignore_permissions=True)
	frappe.db.set_value(
		"Media Specification",
		{"workflow": ["is", "not set"]},
		"workflow",
		workflow.name,
	)
