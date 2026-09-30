import frappe


def after_migrate():
	"""Backfill clip baselines for Timeline Clip rows created before reset support."""
	if not frappe.db.exists("DocType", "Timeline Clip"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabTimeline Clip`
		SET initial_source_in_frame = source_in_frame,
			initial_source_out_frame = source_out_frame
		WHERE COALESCE(initial_source_out_frame, 0) <= COALESCE(initial_source_in_frame, 0)
		"""
	)
