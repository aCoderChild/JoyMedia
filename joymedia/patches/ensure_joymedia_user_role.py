import frappe


def execute():
	if not frappe.db.exists("Role", "JoyMedia User"):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": "JoyMedia User",
				"desk_access": 0,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)
