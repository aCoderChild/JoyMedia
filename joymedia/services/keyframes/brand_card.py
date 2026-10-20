"""Compose a closing take entirely from approved source artwork."""

import tempfile
from pathlib import Path

import frappe
from frappe import _


@frappe.whitelist()
def preserve_closing_art(project_name, expected_take):
	from joymedia.services.editing.composer import (
		_get_asset_version_path,
		_get_delivery_profile,
		_get_or_create_shot_output_asset,
		_select_output,
		_validate_normalized_video,
		hold_brand_card,
	)

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	name = frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		pluck="name",
		order_by="shot_number desc",
		limit_page_length=1,
	)
	if not name:
		frappe.throw(_("There is no closing scene."))
	shot = frappe.get_doc("Shot", name[0])
	from joymedia.services.keyframes.stage import approved_keyframe_task

	if not approved_keyframe_task(shot):
		frappe.throw(_("Approve the closing artwork before composing the packshot."))
	if shot.selected_output_asset_version != expected_take or not expected_take:
		frappe.throw(_("The selected closing take changed. Reload the project."))
	if not any(frappe.scrub(r.reference_role or "") == "product" for r in shot.generation_inputs):
		frappe.throw(_("The closing scene needs a source product reference."))
	image_url = frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file")
	image = frappe.get_doc("File", {"file_url": image_url}).get_full_path()
	profile = _get_delivery_profile(project)
	frames = int(shot.planned_frame_count or round(float(shot.duration_seconds) * profile["fps"]))
	with tempfile.TemporaryDirectory() as directory:
		output = Path(directory) / "source-packshot.mp4"
		hold_brand_card(
			_get_asset_version_path(expected_take), image, output, profile, frames, frames / profile["fps"]
		)
		_validate_normalized_video(output, profile, expected_frames=frames)
		asset = _get_or_create_shot_output_asset(shot, project.name)
		file = frappe.get_doc(
			dict(
				doctype="File",
				file_name=f"{shot.name}-source-packshot.mp4",
				content=output.read_bytes(),
				is_private=1,
				attached_to_doctype="Media Asset",
				attached_to_name=asset.name,
			)
		).insert(ignore_permissions=True)
	version = frappe.get_doc(
		dict(
			doctype="Asset Version",
			media_asset=asset.name,
			file=file.file_url,
			source="Composed",
			duration_seconds=frames / profile["fps"],
			fps=profile["fps"],
			source_generation_attempt=frappe.db.get_value(
				"Asset Version", expected_take, "source_generation_attempt"
			),
		)
	).insert(ignore_permissions=True)
	current = frappe.db.sql(
		"select selected_output_asset_version, keyframe_artifact from `tabShot` where name=%s for update",
		shot.name,
	)[0]
	if current[0] != expected_take or current[1] != shot.keyframe_artifact:
		frappe.throw(_("The closing scene changed during composition. Reload the project."))
	_select_output(shot, version.name)
	frappe.db.commit()
	from joymedia.services.editing.post_production import resume_post_production

	resume_post_production(project.name)
	return {
		"shot": shot.name,
		"asset_version": version.name,
		"source_keyframe": shot.keyframe_artifact,
		"frames": frames,
	}
