import frappe


def execute():
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
