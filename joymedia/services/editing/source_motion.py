"""Animate approved still artwork without redrawing product text or identity."""

import json
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _


@frappe.whitelist()
def compose_source_motion_take(project_name, shot_name, image_version, expected_current, crop=None):
	"""Create an unselected, frame-exact camera move for a stationary source-art scene.

	The scene's authored camera intent supplies the behavior. This is deliberately
	limited to stationary product/identity inserts; action remains in the video
	workflow, and the unchanged source photograph remains available for review.
	"""
	from joymedia.services.consistency.repair import _project_asset_path
	from joymedia.services.editing.composer import (
		_get_delivery_profile,
		_get_or_create_shot_output_asset,
		_validate_normalized_video,
	)
	from joymedia.services.generation.takes import _ensure_scene_free, _project_shot
	from joymedia.services.planning.shot_structure import structure_for
	from joymedia.services.review.admission import digest

	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	if (shot.selected_output_asset_version or None) != (expected_current or None):
		frappe.throw(_("The selected take changed. Reload the scene history."))
	structure = structure_for(shot)
	if (
		not structure
		or structure["subject_motion"] != "stationary"
		or structure["stage"] not in {"establish", "detail", "inspect", "present", "hero"}
	):
		frappe.throw(_("Source camera motion requires an authored stationary product or identity insert."))
	if image_version not in {row.asset_version for row in shot.generation_inputs or []}:
		frappe.throw(_("The source image must be assigned to this scene."))
	version = frappe.get_doc("Asset Version", image_version)
	if frappe.db.get_value("Media Asset", version.media_asset, "media_type") != "Image":
		frappe.throw(_("Source camera motion requires an image."))
	plan = frappe.parse_json(shot.motion_plan_json or "{}") or {}
	intent = plan.get("camera_intent") or {}
	behavior = intent.get("behavior")
	if behavior not in {"push_in", "pull_back", "locked"}:
		frappe.throw(_("This source-art scene needs a single supported camera behavior."))
	profile = _get_delivery_profile(project)
	frames = int(shot.planned_frame_count or round(float(shot.duration_seconds) * profile["fps"]))
	if frames < 1:
		frappe.throw(_("The scene needs a positive frame count."))
	source = _project_asset_path(project, image_version)
	width, height, fps = profile["width"], profile["height"], profile["fps"]
	crop_filter = ""
	if crop is not None:
		from PIL import Image

		if isinstance(crop, str):
			crop = frappe.parse_json(crop)
		if not isinstance(crop, list) or len(crop) != 4 or any(type(n) is not int for n in crop):
			frappe.throw(_("Crop must be four integer source-pixel coordinates."))
		x, y, crop_width, crop_height = crop
		with Image.open(source) as source_image:
			source_width, source_height = source_image.size
		if (
			x < 0
			or y < 0
			or crop_width < 2
			or crop_height < 2
			or x + crop_width > source_width
			or y + crop_height > source_height
			or abs(crop_width / crop_height - width / height) > 0.002
		):
			frappe.throw(_("Crop must stay in the source image and preserve the delivery aspect ratio."))
		crop_filter = f"crop={crop_width}:{crop_height}:{x}:{y},"
	# FFmpeg's standard zoompan preserves every source pixel's design/text while
	# applying only the movement requested by the scene's camera contract.
	progress = f"on/{max(1, frames - 1)}"
	# Match the safe axial travel used by the shared camera prompt. A larger
	# zoom can crop package edges even though the source artwork stays exact.
	travel = 0.06
	zoom = {
		"push_in": f"1+{travel}*{progress}",
		"pull_back": f"{1 + travel}-{travel}*{progress}",
		"locked": "1",
	}[behavior]
	filter_graph = (
		crop_filter + f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
		f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=white,"
		f"zoompan=z='{zoom}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
		f"d=1:s={width}x{height}:fps={fps},format=yuv420p"
	)
	with tempfile.TemporaryDirectory(prefix="joymedia-source-motion-") as directory:
		output = Path(directory) / "source-motion.mp4"
		subprocess.run(
			[
				"ffmpeg",
				"-v",
				"error",
				"-y",
				"-loop",
				"1",
				"-framerate",
				str(fps),
				"-i",
				str(source),
				"-vf",
				filter_graph,
				"-frames:v",
				str(frames),
				"-r",
				str(fps),
				"-c:v",
				"libx264",
				"-crf",
				"14",
				"-pix_fmt",
				"yuv420p",
				str(output),
			],
			check=True,
			capture_output=True,
			timeout=600,
		)
		_validate_normalized_video(output, profile, expected_frames=frames)
		content = output.read_bytes()
	asset = _get_or_create_shot_output_asset(shot, project.name)
	file = frappe.get_doc(
		dict(
			doctype="File",
			file_name=f"{shot.name}-source-motion.mp4",
			content=content,
			is_private=1,
			attached_to_doctype="Media Asset",
			attached_to_name=asset.name,
		)
	).insert(ignore_permissions=True)
	evidence = {
		"method": "ffmpeg_zoompan_source_art",
		"source_asset_version": image_version,
		"source_sha256": version.content_hash,
		"output_sha256": digest(content),
		"behavior": behavior,
		"zoom_fraction": travel if behavior != "locked" else 0,
		"crop": crop,
		"frames": frames,
		"fps": fps,
	}
	take = frappe.get_doc(
		dict(
			doctype="Asset Version",
			media_asset=asset.name,
			file=file.file_url,
			source="Composed",
			derived_from=image_version,
			duration_seconds=frames / fps,
			fps=fps,
			preservation_evidence_json=json.dumps(evidence, sort_keys=True),
		)
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"asset_version": take.name, "selected": False, "evidence": evidence}


@frappe.whitelist()
def compose_held_crop_take(
	project_name, shot_name, attempt_name, expected_source_sha256, crop, expected_current, review_note
):
	"""Keep an aspect-correct close-up from immutable held footage as an unselected take."""
	from joymedia.services.editing.composer import (
		_get_artifact_path,
		_get_delivery_profile,
		_get_or_create_shot_output_asset,
		_inspect_video,
		_validate_normalized_video,
	)
	from joymedia.services.generation.takes import _ensure_scene_free, _project_shot
	from joymedia.services.review.admission import digest

	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	if (shot.selected_output_asset_version or None) != (expected_current or None):
		frappe.throw(_("The selected take changed. Reload the scene history."))
	if not isinstance(review_note, str) or not review_note.strip() or len(review_note) > 2000:
		frappe.throw(_("Describe why this crop resolves the held take's visual defect."))
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	task = frappe.get_doc("Generation Task", attempt.generation_task)
	run = frappe.get_doc("Generation Run", task.generation_run)
	if (
		task.shot != shot.name
		or run.media_project != project.name
		or attempt.status not in {"Failed", "Cancelled"}
		or run.status not in {"Failed", "Cancelled"}
	):
		frappe.throw(_("Choose terminal held footage from this scene."))
	artifact = frappe.get_doc(
		"Generation Artifact", {"generation_attempt": attempt.name, "artifact_role": "Primary Video"}
	)
	source = Path(_get_artifact_path(artifact))
	if digest(source.read_bytes()) != expected_source_sha256:
		frappe.throw(_("Held footage content changed."))
	profile = _get_delivery_profile(project)
	stream = _inspect_video(source)
	if isinstance(crop, str):
		crop = frappe.parse_json(crop)
	if not isinstance(crop, list) or len(crop) != 4 or any(type(n) is not int for n in crop):
		frappe.throw(_("Crop must be four integer source-pixel coordinates."))
	x, y, width, height = crop
	if (
		min(x, y) < 0
		or min(width, height) < 64
		or x + width > stream["width"]
		or y + height > stream["height"]
		or abs(width / height - profile["width"] / profile["height"]) > 0.01
	):
		frappe.throw(_("Crop must stay in frame and preserve the delivery aspect ratio."))
	frames = int(shot.planned_frame_count or round(float(shot.duration_seconds) * profile["fps"]))
	if frames < 1:
		frappe.throw(_("The scene needs a positive frame count."))
	with tempfile.TemporaryDirectory(prefix="joymedia-held-crop-") as directory:
		output = Path(directory) / "review-crop.mp4"
		subprocess.run(
			[
				"ffmpeg",
				"-v",
				"error",
				"-y",
				"-i",
				str(source),
				"-vf",
				f"crop={width}:{height}:{x}:{y},scale={profile['width']}:{profile['height']},setsar=1,fps={profile['fps']}",
				"-frames:v",
				str(frames),
				"-an",
				"-c:v",
				"libx264",
				"-crf",
				"14",
				"-pix_fmt",
				"yuv420p",
				str(output),
			],
			check=True,
			capture_output=True,
			timeout=600,
		)
		_validate_normalized_video(output, profile, expected_frames=frames)
		content = output.read_bytes()
	asset = _get_or_create_shot_output_asset(shot, project.name)
	file = frappe.get_doc(
		dict(
			doctype="File",
			file_name=f"{shot.name}-held-crop.mp4",
			content=content,
			is_private=1,
			attached_to_doctype="Media Asset",
			attached_to_name=asset.name,
		)
	).insert(ignore_permissions=True)
	evidence = {
		"method": "ffmpeg_crop_from_held_inference",
		"source_attempt": attempt.name,
		"source_sha256": expected_source_sha256,
		"output_sha256": digest(content),
		"crop": crop,
		"frames": frames,
		"fps": profile["fps"],
		"review_note": review_note.strip(),
	}
	take = frappe.get_doc(
		dict(
			doctype="Asset Version",
			media_asset=asset.name,
			file=file.file_url,
			source="Composed",
			source_generation_attempt=attempt.name,
			duration_seconds=frames / profile["fps"],
			fps=profile["fps"],
			preservation_evidence_json=json.dumps(evidence, sort_keys=True),
		)
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"asset_version": take.name, "selected": False, "evidence": evidence}
