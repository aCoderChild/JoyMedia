import frappe


def execute():
	_migrate_global_instructions()
	_backfill_video_idea()
	_migrate_reference_templates_to_asset_versions()
	_remove_reference_template_doctype()


def _migrate_global_instructions():
	if not frappe.db.table_exists("Media Specification"):
		return
	if not frappe.db.has_column("Media Specification", "global_instructions"):
		return
	old_fields = [
		fieldname
		for fieldname in ("global_consistency_instructions", "generation_instructions")
		if frappe.db.has_column("Media Specification", fieldname)
	]
	if not old_fields:
		return
	columns = ", ".join(["name", "global_instructions"] + old_fields)
	for row in frappe.db.sql(f"SELECT {columns} FROM `tabMedia Specification`", as_dict=True):
		parts = []
		for value in [row.global_instructions] + [row.get(fieldname) for fieldname in old_fields]:
			text = str(value or "").strip()
			if text and text not in parts:
				parts.append(text)
		if parts:
			frappe.db.set_value(
				"Media Specification", row.name, "global_instructions", "\n\n".join(parts), update_modified=False
			)


def _backfill_video_idea():
	if not frappe.db.table_exists("Media Project"):
		return
	if not (
		frappe.db.has_column("Media Project", "video_idea")
		and frappe.db.has_column("Media Project", "campaign_brief")
	):
		return
	frappe.db.sql(
		"""
		UPDATE `tabMedia Project`
		SET video_idea = campaign_brief
		WHERE (video_idea IS NULL OR TRIM(video_idea) = '')
		  AND campaign_brief IS NOT NULL
		  AND TRIM(campaign_brief) != ''
		"""
	)


def _migrate_reference_templates_to_asset_versions():
	if not frappe.db.table_exists("Video Reference Template"):
		return

	templates = frappe.db.sql(
		"""
		SELECT name, reference_video_asset_version, analysis_status, template_json
		FROM `tabVideo Reference Template`
		""",
		as_dict=True,
	)
	asset_version_by_template = {}
	for template in templates:
		asset_version = template.reference_video_asset_version
		if not asset_version or not frappe.db.exists("Asset Version", asset_version):
			continue
		asset_version_by_template[template.name] = asset_version
		updates = {}
		if template.analysis_status:
			updates["analysis_status"] = template.analysis_status
		if template.template_json:
			updates["analysis_json"] = template.template_json
		if updates:
			frappe.db.set_value("Asset Version", asset_version, updates, update_modified=False)

	if not frappe.db.has_column("Media Project", "reference_template"):
		return
	projects = frappe.db.sql(
		"""
		SELECT name, reference_template
		FROM `tabMedia Project`
		WHERE reference_template IS NOT NULL AND TRIM(reference_template) != ''
		""",
		as_dict=True,
	)
	for row in projects:
		asset_version = asset_version_by_template.get(row.reference_template)
		if not asset_version:
			continue
		project = frappe.get_doc("Media Project", row.name)
		if any(selection.asset_version == asset_version for selection in project.selected_media or []):
			continue
		project.append("selected_media", {"asset_version": asset_version})
		project.save(ignore_permissions=True)


def _remove_reference_template_doctype():
	if frappe.db.exists("DocType", "Video Reference Template"):
		frappe.delete_doc(
			"DocType",
			"Video Reference Template",
			ignore_permissions=True,
			force=True,
		)
