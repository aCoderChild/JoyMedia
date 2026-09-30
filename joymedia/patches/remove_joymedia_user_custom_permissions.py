import frappe


def execute():
	custom_permissions = frappe.get_all(
		"Custom DocPerm",
		filters={"role": "JoyMedia User"},
		pluck="name",
	)
	for permission in custom_permissions:
		frappe.delete_doc(
			"Custom DocPerm",
			permission,
			ignore_permissions=True,
			force=True,
		)
