import frappe


def execute():
	if not frappe.db.table_exists("Media Asset"):
		return
	q = chr(96)
	frappe.db.sql(
		f"""
		UPDATE {q}tabMedia Asset{q}
		SET asset_scope = CASE
			WHEN media_project IS NULL OR media_project = '' THEN 'Library'
			ELSE 'Project Output'
		END
		WHERE asset_scope IS NULL OR asset_scope = ''
		"""
	)
