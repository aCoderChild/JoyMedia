"""Persist already-computed results without replaying inference or network calls."""

import frappe


def persist_result(write, attempts=3):
	"""Run a short database/file-storage promotion in a fresh transaction.

	Only call at a background-result boundary, with expensive work completed and
	no uncommitted user edits. `write` must not submit inference or perform other
	external side effects. Deferred enqueue callbacks are discarded on rollback.
	"""
	if type(attempts) is not int or attempts < 1 or attempts > 5:
		raise ValueError("Persistence attempts must be between one and five.")
	frappe.db.commit()
	for index in range(attempts):
		try:
			result = write()
			frappe.db.commit()
			return result
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if index == attempts - 1:
				raise
		except Exception:
			frappe.db.rollback()
			raise
