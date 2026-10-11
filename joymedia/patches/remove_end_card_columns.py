import frappe


def execute():
	columns = set(frappe.db.get_table_columns("Media Project"))
	for fieldname in ("end_card_title", "end_card_tagline"):
		if fieldname in columns:
			frappe.db.sql(f"ALTER TABLE `tabMedia Project` DROP COLUMN `{fieldname}`")
