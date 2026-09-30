import frappe


def execute():
	for permission in frappe.get_all(
		"User Permission",
		filters={"allow": "Client Organization"},
		pluck="name",
	):
		frappe.delete_doc("User Permission", permission, ignore_permissions=True, force=True)

	for doctype in ("Campaign", "Media Project", "Media Asset"):
		field_name = frappe.db.get_value(
			"DocField",
			{"parent": doctype, "fieldname": "client_organization"},
			"name",
		)
		if field_name:
			frappe.delete_doc("DocField", field_name, ignore_permissions=True, force=True)

	if frappe.db.exists("DocType", "Client Organization"):
		frappe.delete_doc("DocType", "Client Organization", ignore_permissions=True, force=True)
