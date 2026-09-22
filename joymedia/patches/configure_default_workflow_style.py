import frappe


def execute():
	workflow_name = frappe.db.get_value(
		"Workflow",
		{"workflow_code": "MINIMAX-H3", "is_default": 1},
		"name",
	)
	if not workflow_name:
		workflow_name = frappe.db.get_value(
			"Workflow",
			{
				"workflow_code": "MINIMAX-H3",
				"status": ["in", ["Testing", "Production"]],
			},
			"name",
			order_by="version_number desc, modified desc",
		)
	if not workflow_name:
		return

	frappe.db.set_value(
		"Workflow",
		workflow_name,
		{
			"workflow_key": "product_showcase",
			"client_name": "Product Showcase",
			"client_description": "Clean, polished product presentation for launches and ecommerce.",
			"client_visible": 1,
			"is_active": 1,
		},
		update_modified=False,
	)
	frappe.db.set_value("Workflow", {"is_default": 1}, "is_default", 0)
	frappe.db.set_value("Workflow", workflow_name, "is_default", 1)
