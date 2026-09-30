import frappe


def execute():
	for fieldname in ("lifecycle_status", "promoted_asset_version"):
		field_name = frappe.db.get_value(
			"DocField",
			{"parent": "Generation Artifact", "fieldname": fieldname},
			"name",
		)
		if field_name:
			frappe.delete_doc("DocField", field_name, ignore_permissions=True, force=True)
