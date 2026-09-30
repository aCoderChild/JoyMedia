import frappe


def execute():
	"""Remove the obsolete Generation Backend abstraction from existing sites.

	JoyMedia currently executes only through the single ComfyUI endpoint configured
	in ``frappe.conf.comfyui_base_url``. Each Generation Attempt keeps the endpoint
	URL snapshot for provenance, so a separate backend registry is unnecessary.
	"""
	field_name = frappe.db.get_value(
		"DocField",
		{"parent": "Generation Attempt", "fieldname": "generation_backend"},
		"name",
	)
	if field_name:
		frappe.delete_doc("DocField", field_name, ignore_permissions=True, force=True)

	if frappe.db.exists("DocType", "Generation Backend"):
		frappe.delete_doc("DocType", "Generation Backend", ignore_permissions=True, force=True)
