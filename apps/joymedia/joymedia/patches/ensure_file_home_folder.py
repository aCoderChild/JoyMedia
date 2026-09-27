import frappe


def execute():
	from frappe.core.doctype.file.utils import make_home_folder

	if not frappe.db.exists("File", {"is_home_folder": 1}):
		make_home_folder()
