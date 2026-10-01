import frappe


def execute():
	"""Make library files downloadable through their Media Asset permissions."""
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
