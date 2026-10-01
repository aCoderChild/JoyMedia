import frappe


def execute():
	"""Move legacy generated shot outputs and deliverables from Library to Project Output."""
	if not frappe.db.table_exists("Media Asset"):
		return

	# 1. Update any asset explicitly categorized or named as shot output / deliverable / storyboard
	frappe.db.sql(
		"""
		UPDATE `tabMedia Asset`
		SET asset_scope = 'Project Output'
		WHERE
			asset_category IN ('Shot Output', 'Final Deliverable', 'Deliverable', 'Storyboard')
			OR asset_name LIKE '%Shot Output%'
			OR asset_name LIKE '%Final Deliverable%'
			OR asset_name LIKE '%Deliverable%'
			OR asset_name LIKE '%Continuation Frames%'
			OR asset_name LIKE '%Project Video%'
			OR asset_name LIKE '%Final Video%'
		"""
	)

	# 2. Update any Media Asset whose Asset Versions have source 'Generated' or 'Composed'
	frappe.db.sql(
		"""
		UPDATE `tabMedia Asset` ma
		INNER JOIN `tabAsset Version` av ON av.media_asset = ma.name
		SET ma.asset_scope = 'Project Output'
		WHERE av.source IN ('Generated', 'Composed')
		"""
	)

	# 3. Update any Media Asset linked to a Shot as selected_output_asset_version
	frappe.db.sql(
		"""
		UPDATE `tabMedia Asset` ma
		INNER JOIN `tabAsset Version` av ON av.media_asset = ma.name
		INNER JOIN `tabShot` s ON s.selected_output_asset_version = av.name
		SET
			ma.asset_scope = 'Project Output',
			ma.media_project = COALESCE(NULLIF(ma.media_project, ''), s.media_project)
		WHERE s.media_project IS NOT NULL AND s.media_project != ''
		"""
	)

	# 4. Update any Media Asset linked to a Media Project as current_output_asset_version
	frappe.db.sql(
		"""
		UPDATE `tabMedia Asset` ma
		INNER JOIN `tabAsset Version` av ON av.media_asset = ma.name
		INNER JOIN `tabMedia Project` mp ON mp.current_output_asset_version = av.name
		SET
			ma.asset_scope = 'Project Output',
			ma.media_project = COALESCE(NULLIF(ma.media_project, ''), mp.name)
		"""
	)

	# 5. For any remaining Project Output asset without media_project, try to parse from asset_name if PRJ- is present
	rows = frappe.db.sql(
		"""
		SELECT name, asset_name
		FROM `tabMedia Asset`
		WHERE asset_scope = 'Project Output' AND (media_project IS NULL OR media_project = '')
		""",
		as_dict=True,
	)
	for r in rows:
		name_str = r.asset_name or ""
		if "PRJ-" in name_str:
			parts = name_str.split()
			for p in parts:
				if p.startswith("PRJ-") and frappe.db.exists("Media Project", p):
					frappe.db.set_value("Media Asset", r.name, "media_project", p, update_modified=False)
					break

	frappe.db.commit()
