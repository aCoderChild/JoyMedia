import frappe


def execute():
	"""Remove the per-scene verdict model (Shot Review, Shot.review_status); scenes are reviewed with Review Comments."""
	if frappe.db.exists("DocType", "Shot Review"):
		frappe.delete_doc("DocType", "Shot Review", force=True, ignore_permissions=True)
	if frappe.db.table_exists("Shot Review"):
		frappe.db.sql_ddl("DROP TABLE `tabShot Review`")
	if frappe.db.has_column("Shot", "review_status"):
		frappe.db.sql_ddl("ALTER TABLE `tabShot` DROP COLUMN `review_status`")
	frappe.clear_cache(doctype="Shot")
