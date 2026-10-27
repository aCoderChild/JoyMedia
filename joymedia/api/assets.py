# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt


"""HTTP endpoints for selecting a project's image/video/audio references."""

import frappe
from frappe import _

from joymedia.services.project.context import SUPPORTED_PROJECT_MEDIA_TYPES, _get_asset_file_url

REFERENCE_ROLES = {
	"Product",
	"Character",
	"Person",
	"Logo",
	"Environment",
	"Style",
	"Composition",
	"Motion",
	"Audio",
	"General",
}


def _ensure_references_idle(project):
	if frappe.db.exists(
		"Generation Run", {"media_project": project.name, "status": ["in", ["Queued", "Running"]]}
	):
		frappe.throw(_("Project references cannot change while generation is active."))


def _sync_scene_reference(project, asset_version, role=None):
	"""Keep saved shot inputs consistent with a changed or removed project reference."""
	for shot_name in frappe.get_all(
		"Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name"
	):
		shot = frappe.get_doc("Shot", shot_name)
		rows = list(shot.generation_inputs or [])
		if role is None:
			kept = [row for row in rows if row.asset_version != asset_version]
			if len(kept) == len(rows):
				continue
			shot.set("generation_inputs", kept)
		else:
			matched = [row for row in rows if row.asset_version == asset_version]
			if not matched or all(row.reference_role == role for row in matched):
				continue
			for row in matched:
				row.reference_role = role
		shot.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def update_project_reference_metadata(media_project, asset_version, label=None, reference_role=None):
	"""Edit the studio label and role while preserving the source Media Asset."""
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	row = next((item for item in project.selected_media or [] if item.asset_version == asset_version), None)
	if not row:
		frappe.throw(_("This asset is not selected for the project."))
	if label is None and reference_role is None:
		frappe.throw(_("Choose a name or category to update."))
	_ensure_references_idle(project)
	if label is not None:
		label = str(label).strip()
		if not label or len(label) > 140:
			frappe.throw(_("Asset name must be between 1 and 140 characters."))
		row.label = label
	if reference_role is not None:
		reference_role = str(reference_role).strip()
		if reference_role not in REFERENCE_ROLES:
			frappe.throw(_("Choose a valid reference category."))
		media_asset = frappe.db.get_value("Asset Version", asset_version, "media_asset")
		media_type = frappe.db.get_value("Media Asset", media_asset, "media_type") if media_asset else None
		if reference_role == "Audio" and media_type != "Audio":
			frappe.throw(_("Only audio assets can use the Audio category."))
		if reference_role == "Motion" and media_type != "Video":
			frappe.throw(_("Only videos can use the Motion category."))
		if media_type == "Audio" and reference_role != "Audio":
			frappe.throw(_("Audio assets must stay in the Audio category."))
		if row.reference_role != reference_role:
			other_roles = {
				item.reference_role
				for item in project.selected_media or []
				if item.name != row.name and item.identity_key == row.identity_key
			}
			if other_roles and other_roles != {reference_role}:
				frappe.throw(_("All views of one identity must use the same category."))
			row.reference_role = reference_role
	project.save(ignore_permissions=True)
	if reference_role is not None:
		_sync_scene_reference(project, asset_version, reference_role)
	from joymedia.api.storyboard import _mark_storyboard_needs_review

	_mark_storyboard_needs_review(project)
	return {"asset_version": asset_version, "label": row.label, "reference_role": row.reference_role}


@frappe.whitelist()
def analyze_project_camera_references(project_name):
	"""Analyze selected Motion videos using the normal long-job queue."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	from joymedia.services.intake.cinematography import motion_references

	if not list(motion_references(project)):
		frappe.throw(_("Select a video with the Motion role first."))
	frappe.enqueue(
		"joymedia.api.assets.run_camera_reference_analysis",
		queue="long",
		timeout=1800,
		job_id=f"joymedia:camera-reference:{project.name}",
		deduplicate=True,
		enqueue_after_commit=True,
		project_name=project.name,
	)
	return {"project": project.name, "status": "Queued"}


def run_camera_reference_analysis(project_name):
	from joymedia.services.intake.cinematography import ensure_project_camera_analysis

	try:
		ensure_project_camera_analysis(frappe.get_doc("Media Project", project_name))
	finally:
		frappe.db.commit()  # Preserve failed-analysis evidence as well as successful measurements.


@frappe.whitelist()
def review_project_camera_reference(project_name, asset_version, grammar):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	from joymedia.services.intake.cinematography import review_reference

	result = review_reference(project, asset_version, grammar)
	from joymedia.api.storyboard import _mark_storyboard_needs_review

	_mark_storyboard_needs_review(project)
	return result


@frappe.whitelist(methods=["POST"])
def annotate_project_action_reference(project_name, asset_version, source_sha256, clips, limitations=""):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	from joymedia.api.storyboard import _mark_storyboard_needs_review
	from joymedia.services.intake.action_reference import annotate_reference

	result = annotate_reference(project, asset_version, source_sha256, clips, limitations)
	_mark_storyboard_needs_review(project)
	return result


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
		"Media Asset",
		filters=filters,
		fields=["name", "asset_name", "media_type", "asset_category", "media_project"],
		order_by="modified desc",
		limit_page_length=200,
	)
	selected = {row.asset_version for row in project.selected_media or [] if row.asset_version}
	valid_assets = []
	for asset in assets:
		if asset.get("media_project"):
			continue
		version = frappe.db.get_value(
			"Asset Version",
			{"media_asset": asset.name},
			["name", "file", "analysis_status", "source"],
			order_by="version_number desc",
			as_dict=True,
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
def select_project_asset(
	media_project, asset_name, reference_role="Product", label=None, reference_key=None, identity_key=None
):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	asset = frappe.get_doc("Media Asset", asset_name)
	if (
		frappe.session.user != "Administrator"
		and "System Manager" not in frappe.get_roles()
		and asset.owner != project.owner
	):
		frappe.throw(_("That asset belongs to another workspace."), frappe.PermissionError)
	if (
		asset.status != "Active"
		or asset.asset_scope != "Library"
		or asset.media_type not in SUPPORTED_PROJECT_MEDIA_TYPES
	):
		frappe.throw(_("That asset cannot be used as a project reference."))
	version = frappe.db.get_value(
		"Asset Version",
		{"media_asset": asset.name},
		["name", "file"],
		order_by="version_number desc",
		as_dict=True,
	)
	if not version or not version.file:
		frappe.throw(_("The selected asset has no usable version."))
	selected = next((row for row in project.selected_media or [] if row.asset_version == version.name), None)
	if selected:
		selected.reference_role = reference_role or "General"
		selected.label = label or ""
		if reference_key:
			selected.reference_key = reference_key
		if identity_key:
			selected.identity_key = identity_key
		project.save(ignore_permissions=True)
		return {"asset_version": version.name, "selected": True}
	project.append(
		"selected_media",
		{
			"asset_version": version.name,
			"reference_key": reference_key or "",
			"identity_key": identity_key or "",
			"reference_role": reference_role or "General",
			"label": label or "",
		},
	)
	project.save(ignore_permissions=True)
	# A picture added after the sheet was imported takes its name and rules from the References sheet.
	from joymedia.services.intake.references import apply_sheet_references

	apply_sheet_references(project.name)
	return {"asset_version": version.name, "selected": True}


def remove_project_asset(media_project, asset_version):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	_ensure_references_idle(project)
	if not any(row.asset_version == asset_version for row in project.selected_media or []):
		frappe.throw(_("That asset version is not selected for this project."))
	project.set(
		"selected_media", [row for row in project.selected_media or [] if row.asset_version != asset_version]
	)
	project.save(ignore_permissions=True)
	_sync_scene_reference(project, asset_version)
	from joymedia.api.storyboard import _mark_storyboard_needs_review

	_mark_storyboard_needs_review(project)
	return {"removed": True}


# Compatibility names used by the current Vue client. The domain concept is now
# selected project media, not image-only "references".
@frappe.whitelist()
def get_project_reference_candidates(media_project):
	return get_project_asset_candidates(media_project)


@frappe.whitelist()
def select_project_reference(
	media_project, asset_name, reference_role="Product", label=None, reference_key=None, identity_key=None
):
	return select_project_asset(media_project, asset_name, reference_role, label, reference_key, identity_key)


@frappe.whitelist()
def set_reference_identity(media_project, asset_version, identity_key):
	"""Group several selected images as approved views of one canonical identity."""
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	row = next((item for item in project.selected_media or [] if item.asset_version == asset_version), None)
	if not row:
		frappe.throw(_("This image is not a reference of the project."))
	row.identity_key = str(identity_key or "").strip()
	project.save(ignore_permissions=True)
	frappe.db.commit()
	return {"asset_version": asset_version, "identity_key": row.identity_key}


@frappe.whitelist(methods=["POST"])
def set_motion_reference_use(media_project, asset_version, use):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	if use not in {"Camera and actions", "Camera only", "Actions only"}:
		frappe.throw(_("Choose camera, actions, or both."))
	row = next(
		(
			r
			for r in project.selected_media
			if r.asset_version == asset_version and r.reference_role == "Motion"
		),
		None,
	)
	if not row:
		frappe.throw(_("Select a Motion video in this project."))
	asset = frappe.db.get_value("Asset Version", asset_version, "media_asset")
	if frappe.db.get_value("Media Asset", asset, "media_type") != "Video":
		frappe.throw(_("This reference use applies to videos."))
	row.motion_reference_use = use
	project.save(ignore_permissions=True)
	from joymedia.api.storyboard import _mark_storyboard_needs_review

	_mark_storyboard_needs_review(project)
	return {"asset_version": asset_version, "motion_reference_use": use}


@frappe.whitelist()
def set_reference_size(media_project, asset_version, relative_size):
	"""How large a character or product appears next to the others (1 = normal); a kid beside a parent is about 0.4."""
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	try:
		size = float(relative_size)
	except (TypeError, ValueError):
		frappe.throw(_("Relative size must be a number."))
	if not 0.1 <= size <= 2:
		frappe.throw(_("Relative size must be between 0.1 and 2."))
	row = next((r for r in project.selected_media or [] if r.asset_version == asset_version), None)
	if not row:
		frappe.throw(_("This image is not a reference of the project."))
	row.relative_size = size
	project.save(ignore_permissions=True)
	frappe.db.commit()
	return {"asset_version": asset_version, "relative_size": size}


@frappe.whitelist()
def remove_project_reference(media_project, asset_version):
	return remove_project_asset(media_project, asset_version)
