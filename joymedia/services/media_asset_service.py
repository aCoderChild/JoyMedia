# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import mimetypes

import frappe
from frappe import _


INPUT_ASSET_CATEGORIES = {"Product", "Character", "Background", "Brand", "Style", "Reference", "Audio", "Other"}


def detect_media_type(file_doc):
	content_type = (
		getattr(file_doc, "mimetype", None)
		or mimetypes.guess_type(file_doc.file_name or "")[0]
		or getattr(file_doc, "file_type", None)
		or ""
	)
	if content_type.startswith("image/"):
		return "Image"
	if content_type.startswith("video/"):
		return "Video"
	if content_type.startswith("audio/"):
		return "Audio"
	if content_type == "application/pdf" or content_type.startswith("text/"):
		return "Document"
	return "Other"


def _get_duplicate_version(
	content_hash,
	version_name,
	media_type,
	asset_category,
):
	rows = frappe.db.sql(
		"""
		SELECT
			av.name,
			av.media_asset
		FROM `tabAsset Version` av
		INNER JOIN `tabMedia Asset` ma
			ON ma.name = av.media_asset
		WHERE
			av.content_hash = %s
			AND av.name != %s
			AND ma.media_type = %s
			AND ma.asset_category = %s
			AND ma.status = 'Active'
		LIMIT 1
		""",
		(content_hash, version_name, media_type, asset_category),
		as_dict=True,
	)
	return rows[0] if rows else None


@frappe.whitelist()
def create_media_asset(asset_name, asset_category, file_url):
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be signed in to upload media."))
	if asset_category not in INPUT_ASSET_CATEGORIES:
		frappe.throw(_("Uploaded assets must be reference inputs."))

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	if file_doc.owner != frappe.session.user and frappe.session.user != "Administrator":
		frappe.throw(_("You can only attach files uploaded by your account."))
	media_type = detect_media_type(file_doc)

	asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": asset_name,
			"media_type": media_type,
			"asset_category": asset_category,
			"asset_scope": "Library",
			"status": "Active",
		}
	).insert(ignore_permissions=True)
	file_doc.db_set(
		{
			"attached_to_doctype": "Media Asset",
			"attached_to_name": asset.name,
		},
		update_modified=False,
	)
	version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": asset.name,
			"file": file_url,
			"source": "Uploaded",
		}
	).insert(ignore_permissions=True)

	duplicate = _get_duplicate_version(
		version.content_hash,
		version.name,
		media_type,
		asset_category,
	)
	if duplicate:
		frappe.delete_doc("Asset Version", version.name, force=True, ignore_permissions=True)
		frappe.delete_doc("Media Asset", asset.name, force=True, ignore_permissions=True)
		frappe.delete_doc("File", file_doc.name, force=True, ignore_permissions=True)
		return {
			"media_asset": duplicate.media_asset,
			"asset_version": duplicate.name,
			"reused": True,
		}

	frappe.db.commit()
	return {
		"media_asset": asset.name,
		"asset_version": version.name,
		"reused": False,
	}
