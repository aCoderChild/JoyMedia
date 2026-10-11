import frappe


def execute():
	"""Migrate the export tier removed from the customer-facing settings."""
	frappe.db.sql(
		"""
		UPDATE `tabMedia Project`
		SET export_quality = 'Draft 720p'
		WHERE export_quality = 'Standard 1080p'
		"""
	)
