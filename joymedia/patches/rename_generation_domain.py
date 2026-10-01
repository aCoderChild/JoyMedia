import frappe


RENAMES = (
	("Shot Specification", "Shot", {"media_specification": "media_project"}),
	("Shot Input Mapping", "Shot Reference", {"input_role": "reference_role"}),
	("Project Media Selection", "Project Reference", {}),
	(
		"Generation Job",
		"Generation Task",
		{
			"shot_specification": "shot",
			"depends_on_job": "depends_on_task",
			"workflow_version": "workflow",
		},
	),
)


def execute():
	for old_doctype, new_doctype, field_mapping in RENAMES:
		if not frappe.db.table_exists(old_doctype) or not frappe.db.table_exists(new_doctype):
			continue
		_copy_rows(old_doctype, new_doctype, field_mapping)

	# These fields existed on already-migrated tables before the DocType rename.
	_copy_column("Generation Attempt", "generation_job", "generation_task")
	_copy_column("Timeline Clip", "shot_specification", "shot")
	_update_child_parent_types()
	_set_project_reference_defaults()

	for old_doctype, _, _ in RENAMES:
		if frappe.db.exists("DocType", old_doctype):
			frappe.db.delete("DocType", {"name": old_doctype})

	frappe.clear_cache()


def _copy_rows(old_doctype, new_doctype, field_mapping):
	if frappe.db.count(new_doctype):
		return
	old_columns = set(frappe.db.get_table_columns(old_doctype))
	new_columns = set(frappe.db.get_table_columns(new_doctype))
	columns = []
	selected_new_columns = set()
	for column in old_columns:
		target = field_mapping.get(column, column)
		# Prefer an already-migrated column over its legacy alias when both exist.
		if column in field_mapping and target in old_columns:
			continue
		if target in new_columns and target not in selected_new_columns:
			columns.append(column)
			selected_new_columns.add(target)
	if "name" not in columns:
		return

	new_names = [field_mapping.get(column, column) for column in columns]
	columns_sql = ", ".join(f"`{column}`" for column in columns)
	new_columns_sql = ", ".join(f"`{column}`" for column in new_names)
	frappe.db.sql(
		f"INSERT INTO `tab{new_doctype}` ({new_columns_sql}) "
		f"SELECT {columns_sql} FROM `tab{old_doctype}`"
	)


def _copy_column(doctype, old_column, new_column):
	if not frappe.db.table_exists(doctype):
		return
	columns = set(frappe.db.get_table_columns(doctype))
	if old_column in columns and new_column in columns:
		frappe.db.sql(
			f"UPDATE `tab{doctype}` SET `{new_column}` = `{old_column}` "
			f"WHERE (`{new_column}` IS NULL OR `{new_column}` = '') "
			f"AND `{old_column}` IS NOT NULL AND `{old_column}` != ''"
		)


def _update_child_parent_types():
	for doctype, old_parenttype, new_parenttype in (
		("Shot Reference", "Shot Specification", "Shot"),
		("Generation Input", "Generation Job", "Generation Task"),
	):
		if frappe.db.table_exists(doctype):
			if "parenttype" not in frappe.db.get_table_columns(doctype):
				continue
			frappe.db.set_value(doctype, {"parenttype": old_parenttype}, "parenttype", new_parenttype)


def _set_project_reference_defaults():
	if frappe.db.table_exists("Project Reference"):
		frappe.db.set_value(
			"Project Reference",
			{"reference_role": ["is", "not set"]},
			"reference_role",
			"General",
		)
