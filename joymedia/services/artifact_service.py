# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

from pathlib import Path

import frappe
from frappe import _

from .comfyui_client import download_output


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
	if artifact.lifecycle_status in ("Expired", "Deleted"):
		frappe.throw(_("Expired artifacts cannot be promoted."))
	if artifact.storage_backend != "ComfyUI":
		frappe.throw(_("Only ComfyUI artifacts can currently be promoted."))
	if artifact.artifact_role != "Primary Video" or artifact.media_type != "Video":
		frappe.throw(_("Only primary video artifacts can currently be promoted."))
	if not artifact.remote_filename:
		frappe.throw(_("Generation Artifact {0} has no remote filename.").format(artifact.name))
	if not frappe.db.exists(
		"Quality Review", {"generation_artifact": artifact.name, "status": "Approved"}
	):
		frappe.throw(_("Generation Artifact {0} requires an approved Quality Review before promotion.").format(artifact.name))

	attempt = frappe.get_doc("Generation Attempt", artifact.generation_attempt)
	if attempt.status != "Completed":
		frappe.throw(_("Only artifacts from completed Generation Attempts can be promoted."))

	video_bytes = download_output(
		artifact.remote_filename,
		artifact.remote_subfolder or "",
		artifact.remote_file_type or "output",
		base_url=attempt.comfyui_endpoint_url,
	)
	job = frappe.get_doc("Generation Job", attempt.generation_job)
	shot = frappe.get_doc("Shot Specification", job.shot_specification)
	media_specification = frappe.get_doc("Media Specification", shot.media_specification)
	media_asset = _get_or_create_shot_output_asset(shot.name, media_specification.media_project)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": Path(artifact.remote_filename).name,
			"content": video_bytes,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": media_asset.name,
		}
	)
	file_doc.insert(ignore_permissions=True)

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
		# Physical cleanup requires a worker deletion API or an object-storage lifecycle policy.
		artifact.lifecycle_status = "Expired"
		artifact.save(ignore_permissions=True)
	frappe.db.commit()
