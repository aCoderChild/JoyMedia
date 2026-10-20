import frappe


def execute():
	"""Drop the empty tables of the removed Media Specification and Audio Cue DocTypes."""
	for doctype in ("Media Specification", "Audio Cue"):
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True)
		if frappe.db.table_exists(doctype) and not frappe.db.count(doctype):
			frappe.db.sql_ddl(f"DROP TABLE `tab{doctype}`")
	frappe.clear_cache()
