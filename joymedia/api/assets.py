# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt


"""HTTP endpoints for selecting a project's image/video/audio references."""

import frappe
from frappe import _
from joymedia.services.project_context import (
	SUPPORTED_PROJECT_MEDIA_TYPES,
	_get_asset_file_url,
)


@frappe.whitelist()
def get_project_asset_candidates(media_project, media_type=None):
	project = frappe.get_doc("Media Project", media_project)
	project._require_read_access()
	filters = {
		"status": "Active",
		"asset_scope": "Library",
		"asset_category": ["not in", ["Shot Output", "Final Deliverable", "Deliverable", "Storyboard"]],
	}
	if media_type:
		if media_type not in SUPPORTED_PROJECT_MEDIA_TYPES:
			frappe.throw(_("Project references support Image, Video, or Audio assets."))
		filters["media_type"] = media_type
	else:
		filters["media_type"] = ["in", sorted(SUPPORTED_PROJECT_MEDIA_TYPES)]
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		# A library is owned by the project owner. This prevents a user from
		# discovering or attaching another customer's assets through this API.
		filters["owner"] = project.owner
	assets = frappe.get_list(
		"Media Asset", filters=filters,
		fields=["name", "asset_name", "media_type", "asset_category", "media_project"],
		order_by="modified desc", limit_page_length=200,
	)
	selected = {row.asset_version for row in project.selected_media or [] if row.asset_version}
	valid_assets = []
	for asset in assets:
		if asset.get("media_project"):
			continue
		version = frappe.db.get_value(
			"Asset Version", {"media_asset": asset.name}, ["name", "file", "analysis_status", "source"],
			order_by="version_number desc", as_dict=True,
		)
		if version and version.source in ("Generated", "Composed"):
			continue
		asset["asset_version"] = version.name if version else None
		asset["file"] = _get_asset_file_url(asset.name, version.file if version else None)
		asset["analysis_status"] = version.analysis_status if version else None
		asset["selected"] = bool(version and version.name in selected)
		valid_assets.append(asset)
	return valid_assets


@frappe.whitelist()
def select_project_asset(media_project, asset_name, reference_role="Product", label=None, reference_key=None):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	asset = frappe.get_doc("Media Asset", asset_name)
	if (
		frappe.session.user != "Administrator"
		and "System Manager" not in frappe.get_roles()
		and asset.owner != project.owner
	):
		frappe.throw(_("That asset belongs to another workspace."), frappe.PermissionError)
	if asset.status != "Active" or asset.asset_scope != "Library" or asset.media_type not in SUPPORTED_PROJECT_MEDIA_TYPES:
		frappe.throw(_("That asset cannot be used as a project reference."))
	version = frappe.db.get_value(
		"Asset Version", {"media_asset": asset.name}, ["name", "file"], order_by="version_number desc", as_dict=True
	)
	if not version or not version.file:
		frappe.throw(_("The selected asset has no usable version."))
	selected = next((row for row in project.selected_media or [] if row.asset_version == version.name), None)
	if selected:
		selected.reference_role = reference_role or "General"
		selected.label = label or ""
		if reference_key:
			selected.reference_key = reference_key
		project.save(ignore_permissions=True)
		return {"asset_version": version.name, "selected": True}
	project.append(
		"selected_media",
		{
			"asset_version": version.name,
			"reference_key": reference_key or "",
			"reference_role": reference_role or "General",
			"label": label or "",
		},
	)
	project.save(ignore_permissions=True)
	return {"asset_version": version.name, "selected": True}


@frappe.whitelist()
def remove_project_asset(media_project, asset_version):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	if not any(row.asset_version == asset_version for row in project.selected_media or []):
		frappe.throw(_("That asset version is not selected for this project."))
	project.set("selected_media", [row for row in project.selected_media or [] if row.asset_version != asset_version])
	project.save(ignore_permissions=True)
	return {"removed": True}


# Compatibility names used by the current Vue client. The domain concept is now
# selected project media, not image-only "references".
@frappe.whitelist()
def get_project_reference_candidates(media_project):
	return get_project_asset_candidates(media_project)


@frappe.whitelist()
def select_project_reference(media_project, asset_name, reference_role="Product", label=None, reference_key=None):
	return select_project_asset(media_project, asset_name, reference_role, label, reference_key)


@frappe.whitelist()
def remove_project_reference(media_project, asset_version):
	return remove_project_asset(media_project, asset_version)
