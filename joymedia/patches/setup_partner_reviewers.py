import frappe


def execute():
	name = "JoyMedia Reviewer"
	if not frappe.db.exists("Role", name):
		frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 0, "is_custom": 1}).insert(
			ignore_permissions=True
		)
	else:
		# DocType sync can create referenced roles before patches, with desk_access enabled by default.
		role = frappe.get_doc("Role", name)
		if role.desk_access:
			role.desk_access = 0
			role.save(ignore_permissions=True)
