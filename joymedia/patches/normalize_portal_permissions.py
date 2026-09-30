import frappe


def execute():
	for doctype in ("Media Project", "Media Asset"):
		for permission in frappe.get_all(
			"Custom DocPerm",
			filters={"parent": doctype, "role": "JoyMedia User"},
			pluck="name",
		):
			frappe.delete_doc(
				"Custom DocPerm",
				permission,
				ignore_permissions=True,
				force=True,
			)
