import frappe


def execute():
	if not frappe.db.has_column("Media Asset", "library_visibility"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabMedia Asset`
		SET library_visibility = 'Internal'
		WHERE asset_category IN ('Shot Output', 'Storyboard')
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabMedia Asset`
		SET library_visibility = 'Internal'
		WHERE asset_name LIKE '% Continuation Frames'
		"""
	)
