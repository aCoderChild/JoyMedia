import frappe


SEMANTIC_BINDINGS = ("first_frame", "last_frame", "generation_prompt")


def execute():
	if not frappe.db.table_exists("Workflow Binding"):
		return

	frappe.db.sql(
		"""
		DELETE FROM `tabWorkflow Binding`
		WHERE binding_key NOT IN %(binding_keys)s
		""",
		{"binding_keys": SEMANTIC_BINDINGS},
	)
