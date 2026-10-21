"""Animate approved still artwork without redrawing product text or identity."""

import json
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _


@frappe.whitelist()
def compose_source_motion_take(project_name, shot_name, image_version, expected_current):
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
	if not structure or structure["subject_motion"] != "stationary" or structure["stage"] not in {
		"detail", "inspect", "present", "hero"
	}:
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
	# FFmpeg's standard zoompan preserves every source pixel's design/text while
	# applying only the movement requested by the scene's camera contract.
	progress = f"on/{max(1, frames - 1)}"
	zoom = {
		"push_in": f"1+0.16*{progress}",
		"pull_back": f"1.16-0.16*{progress}",
		"locked": "1",
	}[behavior]
	filter_graph = (
		f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
		f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=white,"
		f"zoompan=z='{zoom}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
		f"d=1:s={width}x{height}:fps={fps},format=yuv420p"
	)
	with tempfile.TemporaryDirectory(prefix="joymedia-source-motion-") as directory:
		output = Path(directory) / "source-motion.mp4"
		subprocess.run(
			[
				"ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(fps),
				"-i", str(source), "-vf", filter_graph, "-frames:v", str(frames),
				"-r", str(fps), "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p",
				str(output),
			],
			check=True, capture_output=True, timeout=600,
		)
		_validate_normalized_video(output, profile, expected_frames=frames)
		content = output.read_bytes()
	asset = _get_or_create_shot_output_asset(shot, project.name)
	file = frappe.get_doc(
		dict(
			doctype="File", file_name=f"{shot.name}-source-motion.mp4", content=content,
			is_private=1, attached_to_doctype="Media Asset", attached_to_name=asset.name,
		)
	).insert(ignore_permissions=True)
	evidence = {
		"method": "ffmpeg_zoompan_source_art", "source_asset_version": image_version,
		"source_sha256": version.content_hash, "output_sha256": digest(content),
		"behavior": behavior, "frames": frames, "fps": fps,
	}
	take = frappe.get_doc(
		dict(
			doctype="Asset Version", media_asset=asset.name, file=file.file_url,
			source="Composed", derived_from=image_version,
			duration_seconds=frames / fps, fps=fps,
			preservation_evidence_json=json.dumps(evidence, sort_keys=True),
		)
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"asset_version": take.name, "selected": False, "evidence": evidence}
