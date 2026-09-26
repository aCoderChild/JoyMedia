import base64
import mimetypes
from pathlib import Path

import frappe
from frappe import _


REFERENCE_IMAGE_CATEGORIES = [
	"Product",
	"Character",
	"Background",
	"Brand",
	"Storyboard",
	"Reference",
]


def get_project_image_manifest(media_project: str, *, include_data_url: bool = False):
	organization = frappe.db.get_value("Media Project", media_project, "client_organization")
	if not organization:
		return []
	campaign = frappe.db.get_value("Media Project", media_project, "campaign")

	media_assets = frappe.get_all(
		"Media Asset",
		filters={
			"client_organization": organization,
			"library_visibility": "Visible",
			"media_type": "Image",
			"status": "Active",
			"asset_category": ["in", REFERENCE_IMAGE_CATEGORIES],
		},
		or_filters=[{"media_project": media_project}, {"campaign": campaign}] if campaign else [{"media_project": media_project}],
		fields=["name", "asset_name", "asset_category"],
		order_by="asset_name asc, name asc",
	)
	if not media_assets:
		return []

	asset_versions = frappe.get_all(
		"Asset Version",
		filters={"media_asset": ["in", [asset.name for asset in media_assets]]},
		fields=["name", "media_asset", "version_number", "file"],
		order_by="media_asset asc, version_number desc",
	)
	latest_versions = {}
	for version in asset_versions:
		latest_versions.setdefault(version.media_asset, version)

	manifest = []
	for asset in media_assets:
		version = latest_versions.get(asset.name)
		if not version:
			continue

		image = {
			"index": len(manifest) + 1,
			"media_asset": asset.name,
			"asset_name": asset.asset_name,
			"asset_category": asset.asset_category,
			"asset_version": version.name,
		}

		if include_data_url:
			if not version.file:
				frappe.throw(_("Asset Version {0} has no image file.").format(version.name))

			file_doc = frappe.get_doc("File", {"file_url": version.file})
			file_path = Path(file_doc.get_full_path())
			if not file_path.exists():
				frappe.throw(_("Asset Version file does not exist: {0}").format(version.file))

			mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
			encoded_file = base64.b64encode(file_path.read_bytes()).decode("ascii")
			image["data_url"] = f"data:{mime_type};base64,{encoded_file}"

		manifest.append(image)

	return manifest
