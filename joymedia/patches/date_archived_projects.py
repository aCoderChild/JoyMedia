import frappe


def execute():
	# Projects archived before the trash existed get the full retention period from now.
	frappe.db.sql(
		"""update `tabMedia Project` set archived_on = %s
		where status = 'Archived' and archived_on is null""",
		frappe.utils.now_datetime(),
	)
