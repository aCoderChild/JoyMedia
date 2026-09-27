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
	from joymedia.joymedia.doctype.media_project.media_project import _get_project_selected_assets

	project = frappe.get_doc("Media Project", media_project)
	selected_assets = [
		asset for asset in _get_project_selected_assets(project)
		if asset.get("asset_category") in REFERENCE_IMAGE_CATEGORIES
	]
	if not selected_assets:
		return []

	manifest = []
	for asset in selected_assets:
		image = {
			"index": len(manifest) + 1,
			"media_asset": asset["media_asset"],
			"asset_name": asset["asset_name"],
			"asset_category": asset["asset_category"],
			"asset_version": asset["asset_version"],
		}

		if include_data_url:
			if not asset["file"]:
				frappe.throw(_("Asset Version {0} has no image file.").format(asset["asset_version"]))

			file_doc = frappe.get_doc("File", {"file_url": asset["file"]})
			file_path = Path(file_doc.get_full_path())
			if not file_path.exists():
				frappe.throw(_("Asset Version file does not exist: {0}").format(version.file))

			mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
			encoded_file = base64.b64encode(file_path.read_bytes()).decode("ascii")
			image["data_url"] = f"data:{mime_type};base64,{encoded_file}"

		manifest.append(image)

	return manifest
