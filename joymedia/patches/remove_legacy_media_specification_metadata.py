import frappe


def execute():
	"""Remove stale metadata left after the legacy DocType table was removed."""
	frappe.db.sql("DELETE FROM `tabDocType` WHERE name=%s", "Media Specification")
	frappe.clear_cache()
