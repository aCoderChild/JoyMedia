import frappe


def execute():
	"""Treat every legacy selected reference as its own canonical identity."""
	frappe.db.sql(
		"""
		UPDATE `tabProject Reference`
		SET identity_key = reference_key
		WHERE COALESCE(identity_key, '') = '' AND COALESCE(reference_key, '') != ''
		"""
	)
