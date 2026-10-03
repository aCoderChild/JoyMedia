import frappe

from .register_minimax_h3_workflows import execute as register_minimax_h3_workflows


def execute():
	register_minimax_h3_workflows()
	continuation = frappe.db.get_value(
		"Generation Workflow",
		{"workflow_key": "h3_sato_continuation"},
		"name",
		order_by="version_number desc, modified desc",
	)
	if not continuation:
		return

	for workflow_key in ("h3_r2v_production", "h3_r2v_turbo"):
		workflow_name = frappe.db.get_value(
			"Generation Workflow",
			{"workflow_key": workflow_key},
			"name",
			order_by="version_number desc, modified desc",
		)
		if workflow_name:
			frappe.db.set_value(
				"Generation Workflow",
				workflow_name,
				"continuation_workflow",
				continuation,
				update_modified=False,
			)

	frappe.db.set_value(
		"Generation Workflow",
		{"workflow_key": "h3_i2v_production"},
		"continuation_workflow",
		None,
		update_modified=False,
	)
