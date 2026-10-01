import frappe


def execute():
	"""Repair Generation Input rows so they are real Generation Task children.

	Older installations created these rows as standalone documents before the
	Generation Task.inputs table field existed.  The migration is deliberately
	idempotent so fresh and already-repaired sites are both safe.
	"""
	if not frappe.db.table_exists("Generation Input"):
		return

	table = "`tabGeneration Input`"
	columns = set(frappe.db.get_table_columns("Generation Input"))
	for column in ("parent", "parenttype", "parentfield", "idx"):
		if column in columns:
			continue
		column_type = "int" if column == "idx" else "varchar(140)"
		frappe.db.sql(f"ALTER TABLE {table} ADD COLUMN `{column}` {column_type}")

	columns = set(frappe.db.get_table_columns("Generation Input"))
	owner_column = "generation_task" if "generation_task" in columns else None
	if not owner_column and "generation_job" in columns:
		owner_column = "generation_job"
	if not owner_column:
		return

	rows = frappe.db.sql(
		f"""
		SELECT name, `{owner_column}` AS owner
		FROM {table}
		WHERE `{owner_column}` IS NOT NULL AND `{owner_column}` != ''
		ORDER BY `{owner_column}`, creation, name
		""",
		as_dict=True,
	)
	indexes = {}
	for row in rows:
		if not frappe.db.exists("Generation Task", row.owner):
			continue
		indexes[row.owner] = indexes.get(row.owner, 0) + 1
		frappe.db.sql(
			f"""
			UPDATE {table}
			SET parent=%s, parenttype='Generation Task', parentfield='inputs', idx=%s
			WHERE name=%s
			""",
			(row.owner, indexes[row.owner], row.name),
		)
