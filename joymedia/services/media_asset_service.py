# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import mimetypes

import frappe
from frappe import _
from frappe.utils import cint


MIN_REFERENCE_IMAGE_EDGE = 640
INPUT_ASSET_CATEGORIES = {"Product", "Character", "Background", "Brand", "Style", "Reference", "Audio", "Other"}


def _require_asset_action_access(asset):
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be signed in to manage media assets."))
	asset.check_permission("write")


def _get_asset_project_usage(media_asset):
	return frappe.db.sql(
		"""
		SELECT DISTINCT
			pr.parent AS project_name,
			av.name AS asset_version
		FROM `tabProject Reference` pr
		INNER JOIN `tabAsset Version` av ON av.name = pr.asset_version
		WHERE pr.parenttype = 'Media Project'
			AND av.media_asset = %s
		""",
		(media_asset,),
		as_dict=True,
	)


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
def create_media_asset(asset_name, asset_category, file_url=None, file_name=None):
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be signed in to upload media."))
	if not set(frappe.get_roles(frappe.session.user)).intersection(
		{"JoyMedia User", "JoyMedia Specialist", "System Manager"}
	):
		frappe.throw(_("You do not have permission to add media assets."))
	if asset_category not in INPUT_ASSET_CATEGORIES:
		frappe.throw(_("Uploaded assets must be reference inputs."))

	file_doc = frappe.get_doc("File", file_name) if file_name else frappe.get_doc("File", {"file_url": file_url})
	if file_doc.owner != frappe.session.user and frappe.session.user != "Administrator":
		frappe.throw(_("You can only attach files uploaded by your account."))
	media_type = detect_media_type(file_doc)
	if media_type in {"Document", "Other"}:
		frappe.throw(_("Only image, video, or audio files can be added to the media library."))
	from frappe.utils.file_manager import get_max_file_size
	if file_doc.file_size and file_doc.file_size > get_max_file_size():
		frappe.throw(_("This file is larger than the configured upload limit."))

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
	# Small images still work as references, but identity and detail suffer, so the
	# upload is kept and flagged for the UI to warn about instead of being rejected.
	low_resolution = media_type == "Image" and min(cint(version.width), cint(version.height)) < MIN_REFERENCE_IMAGE_EDGE

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
			"low_resolution": low_resolution,
		}

	return {
		"media_asset": asset.name,
		"asset_version": version.name,
		"reused": False,
		"low_resolution": low_resolution,
	}


@frappe.whitelist()
def archive_media_asset(media_asset, detach_projects=False):
	asset = frappe.get_doc("Media Asset", media_asset)
	_require_asset_action_access(asset)
	if asset.asset_scope != "Library":
		frappe.throw(_("Only library assets can be archived from the Media Library."))
	if asset.status == "Archived":
		return {"archived": True, "already_archived": True, "projects": []}

	projects = _get_asset_project_usage(asset.name)
	if projects and not cint(detach_projects):
		return {
			"archived": False,
			"in_use": True,
			"projects": sorted({row.project_name for row in projects}),
		}

	if projects:
		for project_name in sorted({row.project_name for row in projects}):
			project = frappe.get_doc("Media Project", project_name)
			project._require_write_access()
			project.set(
				"selected_media",
				[
					row
					for row in project.selected_media or []
					if frappe.db.get_value("Asset Version", row.asset_version, "media_asset") != asset.name
				],
			)
			project.save(ignore_permissions=True)

	asset.db_set("status", "Archived", update_modified=True)
	return {"archived": True, "in_use": bool(projects), "projects": sorted({row.project_name for row in projects})}


@frappe.whitelist()
def restore_media_asset(media_asset):
	asset = frappe.get_doc("Media Asset", media_asset)
	_require_asset_action_access(asset)
	if asset.asset_scope != "Library":
		frappe.throw(_("Only library assets can be restored."))
	asset.db_set("status", "Active", update_modified=True)
	return {"restored": True, "media_asset": asset.name}
