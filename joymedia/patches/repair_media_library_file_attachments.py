import frappe


def execute():
	"""Attach private library files to their global Media Asset."""
	if not frappe.db.table_exists("File") or not frappe.db.table_exists("Asset Version"):
		return

	rows = frappe.db.sql(
		"""
		SELECT DISTINCT
			f.name,
			av.media_asset
		FROM `tabFile` f
		INNER JOIN `tabAsset Version` av
			ON av.file = f.file_url
		INNER JOIN `tabMedia Asset` ma
			ON ma.name = av.media_asset
		WHERE
			f.is_private = 1
			AND ma.asset_scope = 'Library'
			AND ma.status = 'Active'
			AND (f.attached_to_doctype IS NULL OR f.attached_to_name IS NULL)
		""",
		as_dict=True,
	)
	for row in rows:
		frappe.db.set_value(
			"File",
			row.name,
			{
				"attached_to_doctype": "Media Asset",
				"attached_to_name": row.media_asset,
			},
			update_modified=False,
		)
