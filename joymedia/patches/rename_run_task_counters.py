import frappe


def execute():
	if not frappe.db.table_exists("Generation Run"):
		return
	columns = set(frappe.db.get_table_columns("Generation Run"))
	for old, new in (
		("total_jobs", "total_tasks"),
		("completed_jobs", "completed_tasks"),
		("failed_jobs", "failed_tasks"),
		("running_jobs", "running_tasks"),
	):
		if old in columns and new in columns:
			frappe.db.sql(
				f"UPDATE `tabGeneration Run` SET `{new}`=`{old}` "
				f"WHERE (`{new}` IS NULL OR `{new}`=0) AND `{old}` IS NOT NULL"
			)
