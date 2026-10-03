import frappe


def execute():
	if frappe.db.exists("DocType", "Website Settings"):
		frappe.db.set_single_value("Website Settings", "disable_signup", 1)
