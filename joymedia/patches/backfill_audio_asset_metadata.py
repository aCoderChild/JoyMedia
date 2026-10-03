import frappe


def execute():
	for version in frappe.get_all(
		"Asset Version",
		fields=["name", "media_asset", "duration_seconds"],
	):
		if version.duration_seconds:
			continue
		media_type = frappe.db.get_value("Media Asset", version.media_asset, "media_type")
		if media_type != "Audio":
			continue

		asset_version = frappe.get_doc("Asset Version", version.name)
		try:
			asset_version.set_audio_metadata()
		except Exception:
			frappe.log_error(
				title=f"Unable to backfill audio metadata for {version.name}",
			)
			continue

		frappe.db.set_value(
			"Asset Version",
			version.name,
			{
				"duration_seconds": asset_version.duration_seconds,
				"fps": 0,
			},
			update_modified=False,
		)
