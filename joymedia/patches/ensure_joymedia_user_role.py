import frappe
from frappe import permissions


def execute():
	if frappe.db.exists("Role", "JoyMedia User"):
		role_created = False
	else:
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": "JoyMedia User",
				"desk_access": 0,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)
		role_created = True

	for doctype in ("Client Organization", "Media Project", "Media Asset"):
		for fieldname in ("read", "create", "write"):
			if role_created or not frappe.db.exists(
				"Custom DocPerm",
				{"parent": doctype, "role": "JoyMedia User", fieldname: 1},
			):
				permissions.add_permission(doctype, "JoyMedia User", ptype=fieldname)
