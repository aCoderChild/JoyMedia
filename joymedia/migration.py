import frappe


def after_migrate():
	_ensure_home_folder()

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


def _ensure_home_folder():
	if not frappe.db.exists("File", {"is_home_folder": 1}):
		from frappe.core.doctype.file.utils import make_home_folder
		make_home_folder()
