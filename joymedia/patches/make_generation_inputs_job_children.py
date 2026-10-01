import frappe


def execute():
	"""Attach legacy standalone Generation Input rows to their owning Generation Task."""
	if not frappe.db.table_exists("Generation Input"):
		return
	if not all(
		frappe.db.has_column("Generation Input", column)
		for column in ("generation_task", "parent", "parenttype", "parentfield", "idx")
	):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, generation_task, parent, idx
		FROM `tabGeneration Input`
		ORDER BY generation_task, creation, name
		""",
		as_dict=True,
	)
	indexes = {}
	for row in rows:
		job = row.generation_task or row.parent
		if not job or not frappe.db.exists("Generation Task", job):
			continue
		indexes[job] = indexes.get(job, 0) + 1
		frappe.db.sql(
			"""
			UPDATE `tabGeneration Input`
			SET parent=%s, parenttype='Generation Task', parentfield='inputs', idx=%s, generation_task=%s
			WHERE name=%s
			""",
			(job, indexes[job], job, row.name),
		)
