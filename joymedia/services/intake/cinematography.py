"""Reference camera evidence using CameraPath Lab's pinned analysis core.

Image-space measurements inform review; they never masquerade as a solved 3D
path or a workflow conditioning channel. Reviewed stage preferences use the
existing camera grammar and the existing generation safety compiler.
"""

import hashlib
import json
from pathlib import Path

import frappe

from joymedia.services.planning.camera import normalize_camera_grammar

UPSTREAM_REVISION = "a7d1ddd7c2d78ea772a01ecc612e679034d5da23"
ANALYSIS_VERSION = 1


def analyze_video(path):
	from joymedia.vendor.camerapath.tracking.shot_motion import analyze_shot_motion
	from joymedia.vendor.camerapath.video.ffprobe import probe_frames, probe_video
	from joymedia.vendor.camerapath.video.shots import detect_shots

	path = Path(path)
	with path.open("rb") as stream:
		digest = hashlib.file_digest(stream, "sha256").hexdigest()
	info = probe_video(path)
	frames, info = probe_frames(info)
	shots, _candidates = detect_shots(info, frames)
	results = []
	for shot in shots:
		motion = analyze_shot_motion(info, shot, frames, long_edge=480)
		results.append(
			{
				"shot": shot.model_dump(mode="json"),
				"signature": motion.signature.model_dump(mode="json"),
				"analysis_size": list(motion.analysis_size),
				"warnings": motion.warnings,
			}
		)
	return {
		"version": ANALYSIS_VERSION,
		"upstream_revision": UPSTREAM_REVISION,
		"source": {"name": path.name, "sha256": digest},
		"video": info.model_dump(mode="json", exclude={"path"}),
		"shots": results,
		"measurement_space": "image_space_only",
		"limitation": "No 3D pose or lens solve. Subject motion and synthetic transitions can confound tracking.",
	}


def motion_references(project, *, purpose=None):
	"""Only explicitly selected Motion videos control cinematography."""
	for row in project.get("selected_media") or []:
		if row.get("reference_role") != "Motion" or not row.get("asset_version"):
			continue
		use = row.get("motion_reference_use") or "Camera and actions"
		if (purpose == "Camera" and use == "Actions only") or (purpose == "Actions" and use == "Camera only"):
			continue
		version = frappe.db.get_value(
			"Asset Version",
			row.get("asset_version"),
			["name", "media_asset", "file", "analysis_json"],
			as_dict=True,
		)
		if version and frappe.db.get_value("Media Asset", version.media_asset, "media_type") == "Video":
			yield version


def ensure_project_camera_analysis(project):
	"""Runs in the existing background planning job, never at prompt compilation."""
	for version in motion_references(project, purpose="Camera"):
		stored = frappe.parse_json(version.analysis_json or "{}") or {}
		analysis = stored.get("cinematography") or {}
		if (
			analysis.get("upstream_revision") == UPSTREAM_REVISION
			and analysis.get("version") == ANALYSIS_VERSION
		):
			continue
		file = frappe.get_doc("File", {"file_url": version.file})
		frappe.get_doc("Media Asset", version.media_asset).check_permission("write")
		try:
			stored["cinematography"] = analyze_video(file.get_full_path())
		except Exception as exc:
			frappe.db.set_value(
				"Asset Version",
				version.name,
				{
					"analysis_status": "Failed",
					"analysis_error": str(exc)[:500],
				},
				update_modified=False,
			)
			raise
		# An older review cannot silently approve evidence produced by another analyzer.
		stored.pop("camera_grammar", None)
		frappe.db.set_value(
			"Asset Version",
			version.name,
			{
				"analysis_status": "Ready",
				"analysis_error": None,
				"analysis_json": json.dumps(stored, ensure_ascii=False),
			},
			update_modified=False,
		)


def reference_direction(project):
	profiles, observations = [], []
	for version in motion_references(project, purpose="Camera"):
		stored = frappe.parse_json(version.analysis_json or "{}") or {}
		analysis = stored.get("cinematography") or {}
		if (
			analysis.get("upstream_revision") != UPSTREAM_REVISION
			or analysis.get("version") != ANALYSIS_VERSION
		):
			raise ValueError("Analyze the selected Motion video before planning cinematography.")
		# A cut detector does not detect semantic coverage phases within a continuous take.
		observations.append(
			f"Reference {analysis['source']['name']}: {len(analysis['shots'])} detected continuous shot(s). "
			"Internal coverage changes are not additional detected cuts. Measurements are image-space only; "
			"do not infer metric travel, orbit or zoom from optical flow alone."
		)
		for row in analysis["shots"][:4]:
			signature = row["signature"]
			width, height = row["analysis_size"]
			observations.append(
				f"Measured image-motion rhythm at {width}x{height}: "
				f"mean {signature['mean_flow_magnitude']:.2f}, peak {signature['peak_flow_magnitude']:.2f} px/frame; "
				f"model agreement {signature['mean_inlier_ratio']:.0%}. "
				"This is reference evidence, not a required speed for the target scene or proof of camera translation."
			)
		if stored.get("camera_grammar"):
			profiles.append(normalize_camera_grammar(stored["camera_grammar"]))
	return profiles, observations


def review_reference(project, asset_version, grammar):
	"""Attach an explicit editorial interpretation to analyzed, selected evidence."""
	version = next((v for v in motion_references(project, purpose="Camera") if v.name == asset_version), None)
	if not version:
		raise ValueError("Select this video as a Motion reference in this project first.")
	frappe.get_doc("Media Asset", version.media_asset).check_permission("write")
	stored = frappe.parse_json(version.analysis_json or "{}") or {}
	analysis = stored.get("cinematography") or {}
	if analysis.get("upstream_revision") != UPSTREAM_REVISION or analysis.get("version") != ANALYSIS_VERSION:
		raise ValueError("Analyze this reference before reviewing its camera direction.")
	grammar = normalize_camera_grammar(grammar)
	if not grammar or analysis["source"]["sha256"] not in {s["sha256"] for s in grammar["sources"]}:
		raise ValueError("Reviewed grammar must include the analyzed video's source hash.")
	stored["camera_grammar"] = grammar
	frappe.db.set_value(
		"Asset Version", version.name, "analysis_json", json.dumps(stored, ensure_ascii=False)
	)
	return grammar
