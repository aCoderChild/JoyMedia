import frappe


def execute():
	for asset in frappe.get_all(
		"Media Asset",
		filters={"asset_scope": "Project"},
		fields=["name", "media_project"],
	):
		if asset.media_project:
			frappe.db.set_value(
				"Media Asset",
				asset.name,
				"client_organization",
				frappe.db.get_value("Media Project", asset.media_project, "client_organization"),
				update_modified=False,
			)

	for attempt in frappe.get_all(
		"Generation Attempt",
		filters={"output_asset_version": ["is", "set"]},
		pluck="output_asset_version",
	):
		if media_asset := frappe.db.get_value("Asset Version", attempt, "media_asset"):
			frappe.db.set_value(
				"Media Asset", media_asset, "asset_category", "Shot Output", update_modified=False
			)

	for composition in frappe.get_all(
		"Media Composition",
		filters={"output_asset_version": ["is", "set"]},
		pluck="output_asset_version",
	):
		if media_asset := frappe.db.get_value("Asset Version", composition, "media_asset"):
			frappe.db.set_value(
				"Media Asset", media_asset, "asset_category", "Final Deliverable", update_modified=False
			)
