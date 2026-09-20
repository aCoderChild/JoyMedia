# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

from pathlib import Path

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

@frappe.whitelist()
def stream_review_artifact(quality_review_name: str):
	"""Return an inline preview of a temporary ComfyUI video for its Quality Review."""
	frappe.has_permission("Quality Review", "read", quality_review_name, throw=True)
	review = frappe.get_doc("Quality Review", quality_review_name)
	if not review.generation_artifact:
		frappe.throw(_("Quality Review {0} has no Generation Artifact.").format(review.name))

	artifact = frappe.get_doc("Generation Artifact", review.generation_artifact)
	if artifact.lifecycle_status != "Temporary":
		frappe.throw(_("Only Temporary Generation Artifacts can be previewed."))
	if artifact.expires_at and get_datetime(artifact.expires_at) <= now_datetime():
		frappe.throw(_("Generation Artifact {0} has expired.").format(artifact.name))
	if artifact.media_type != "Video":
		frappe.throw(_("Only video artifacts can currently be previewed."))

	if artifact.frappe_file:
		file_doc = frappe.get_doc("File", {"file_url": artifact.frappe_file})
		frappe.local.response.filename = Path(file_doc.file_name).name
		frappe.local.response.filecontent = file_doc.get_content()
		frappe.local.response.content_type = "video/mp4"
		frappe.local.response.display_content_as = "inline"
		frappe.local.response.type = "download"
		return

	if not artifact.frappe_file:
		frappe.throw(_("Generation Artifact {0} has no available video file.").format(artifact.name))


@frappe.whitelist()
def promote_artifact_from_ui(artifact_name: str):
	frappe.has_permission("Generation Artifact", "write", artifact_name, throw=True)
	result = promote_artifact(artifact_name)
	frappe.db.commit()
	return result


def promote_artifact(artifact_name: str):
	"""Persist an approved ComfyUI artifact as a project-scoped shot-output asset."""
	artifact = frappe.get_doc("Generation Artifact", artifact_name)

	if artifact.lifecycle_status == "Promoted":
		if not artifact.promoted_asset_version:
			frappe.throw(_("Promoted artifact {0} has no Asset Version.").format(artifact.name))
		return {"asset_version": artifact.promoted_asset_version}
	if artifact.media_type != "Video":
		frappe.throw(_("Only video artifacts can currently be promoted."))
	if not artifact.frappe_file:
		frappe.throw(_("Generation Artifact {0} has no Frappe video file.").format(artifact.name))
	if artifact.expires_at and get_datetime(artifact.expires_at) <= now_datetime():
		frappe.throw(_("Generation Artifact {0} has expired.").format(artifact.name))
	if not frappe.db.exists(
		"Quality Review", {"generation_artifact": artifact.name, "status": "Approved"}
	):
		frappe.throw(_("Generation Artifact {0} requires an approved Quality Review before promotion.").format(artifact.name))

	attempt = frappe.get_doc("Generation Attempt", artifact.generation_attempt)
	if attempt.status != "Completed":
		frappe.throw(_("Only artifacts from completed Generation Attempts can be promoted."))

	job = frappe.get_doc("Generation Job", attempt.generation_job)
	shot = frappe.get_doc("Shot Specification", job.shot_specification)
	media_specification = frappe.get_doc("Media Specification", shot.media_specification)
	media_asset = _get_or_create_shot_output_asset(shot.name, media_specification.media_project)

	if artifact.frappe_file:
		file_doc = frappe.get_doc("File", {"file_url": artifact.frappe_file})
		file_doc.attached_to_doctype = "Media Asset"
		file_doc.attached_to_name = media_asset.name
		file_doc.save(ignore_permissions=True)
	else:
		frappe.throw(_("Generation Artifact {0} has no Frappe video file.").format(artifact.name))

	asset_version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": media_asset.name,
			"file": file_doc.file_url,
			"source": "Generated",
		}
	)
	asset_version.insert(ignore_permissions=True)

	artifact.lifecycle_status = "Promoted"
	artifact.promoted_asset_version = asset_version.name
	artifact.save(ignore_permissions=True)
	attempt.output_asset_version = asset_version.name
	attempt.save(ignore_permissions=True)
	return {"asset_version": asset_version.name}


def _get_or_create_shot_output_asset(shot_name, media_project):
	asset_name = f"{shot_name} Generated Video"
	media_asset_name = frappe.db.get_value("Media Asset", {"asset_name": asset_name}, "name")
	if media_asset_name:
		return frappe.get_doc("Media Asset", media_asset_name)

	media_asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": asset_name,
			"asset_scope": "Project",
			"media_type": "Video",
			"asset_category": "Shot Output",
			"media_project": media_project,
		}
	)
	media_asset.insert(ignore_permissions=True)
	return media_asset


def expire_generation_artifacts():
	"""Logically expire temporary artifacts; remote content is not deleted in Phase 1."""
	artifacts = frappe.get_all(
		"Generation Artifact",
		filters={
			"lifecycle_status": "Temporary",
			"expires_at": ["<", frappe.utils.now()],
		},
		pluck="name",
	)
	for name in artifacts:
		artifact = frappe.get_doc("Generation Artifact", name)
		if artifact.frappe_file:
			file_name = frappe.db.get_value("File", {"file_url": artifact.frappe_file}, "name")
			if file_name:
				frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
	frappe.db.commit()
