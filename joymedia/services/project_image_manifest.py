import base64
import mimetypes
from pathlib import Path

import frappe
from frappe import _


REFERENCE_IMAGE_CATEGORIES = ["Product", "Character", "Background", "Brand", "Style", "Reference"]


def get_project_image_manifest(media_project: str, *, include_data_url: bool = False):
	"""Return only selected image Asset Versions used as visual generation inputs."""
	from joymedia.services.project_context import _get_project_selected_assets

	project = frappe.get_doc("Media Project", media_project)
	selected_assets = [
		asset for asset in _get_project_selected_assets(project)
		if asset.get("media_type") == "Image"
		and asset.get("asset_category") in REFERENCE_IMAGE_CATEGORIES
	]
	manifest = []
	for asset in selected_assets:
		asset_version = frappe.get_doc("Asset Version", asset["asset_version"])
		image = {
			"index": len(manifest) + 1,
			"media_asset": asset["media_asset"],
			"asset_name": asset["asset_name"],
			"asset_category": asset["asset_category"],
			"asset_version": asset["asset_version"],
			"reference_key": asset.get("reference_key") or "",
		}
		if include_data_url:
			if not asset_version.file:
				frappe.throw(_("Asset Version {0} has no image file.").format(asset_version.name))
			file_doc = frappe.get_doc("File", {"file_url": asset_version.file})
			file_path = Path(file_doc.get_full_path())
			if not file_path.exists():
				frappe.throw(_("Asset Version file does not exist: {0}").format(asset_version.file))
			mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
			encoded_file = base64.b64encode(file_path.read_bytes()).decode("ascii")
			image["data_url"] = f"data:{mime_type};base64,{encoded_file}"
		manifest.append(image)
	return manifest
