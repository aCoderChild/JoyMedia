import frappe


def execute():
	for fieldname in ("end_card_title", "end_card_tagline"):
		if frappe.db.has_column("Media Project", fieldname):
			frappe.db.sql(f"ALTER TABLE `tabMedia Project` DROP COLUMN `{fieldname}`")
