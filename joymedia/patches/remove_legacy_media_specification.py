import frappe


def execute():
	"""Remove legacy Media Specification records and its DocType."""
	if frappe.db.table_exists("Media Specification"):
		frappe.db.sql("DELETE FROM `tabMedia Specification`")
	if frappe.db.exists("DocType", "Media Specification"):
		frappe.delete_doc("DocType", "Media Specification", force=True, ignore_permissions=True)
	frappe.clear_cache()
