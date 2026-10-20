"""Reviewed planar artwork repair for opening images, using the existing OpenCV controls.

Only printed surfaces are projected. The generated object's geometry, opening,
contact shadow and environment are not replaced by a catalogue photograph.
"""

import hashlib
import json
from pathlib import Path

import frappe


def _opening(project_name, shot_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw("Shot does not belong to this project.", frappe.PermissionError)
	frames = [
		r.asset_version
		for r in shot.generation_inputs
		if frappe.scrub(r.reference_role or "") == "first_frame"
	]
	if len(frames) > 1:
		frappe.throw("Choose one opening image.")
	if frames:
		version = frappe.get_doc("Asset Version", frames[0])
		url, identity = version.file, {"asset_version": version.name}
	elif shot.keyframe_artifact:
		from joymedia.services.keyframes.stage import keyframe_signature

		if shot.keyframe_signature != keyframe_signature(shot):
			frappe.throw("The opening image is stale. Redraw it first.")
		url = frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file")
		identity = {"artifact": shot.keyframe_artifact}
	else:
		frappe.throw("Draw an opening image first.")
	content = Path(frappe.get_doc("File", {"file_url": url}).get_full_path()).read_bytes()
	return project, shot, url, content, {**identity, "sha256": hashlib.sha256(content).hexdigest()}


@frappe.whitelist()
def get_opening_art_source(project_name, shot_name):
	_project, _shot, url, _content, token = _opening(project_name, shot_name)
	return {"file": url, "expected_frame": token}


def project_surface(background, artwork, source_quad, target_quad, *, blend_mode="source"):
	"""Same polygon/homography/alpha primitives as consistency.tracking.restore_video."""
	import cv2
	import numpy as np

	from joymedia.services.consistency.tracking import PreservationError, quad

	if background is None or artwork is None or artwork.ndim != 3 or artwork.shape[2] not in (3, 4):
		raise PreservationError("Artwork must be an RGB or RGBA image.")
	h, w = background.shape[:2]
	if max(w * h, artwork.shape[0] * artwork.shape[1]) > 4096 * 4096:
		raise PreservationError("Artwork exceeds the restoration pixel budget.")
	source = quad(source_quad, (artwork.shape[1], artwork.shape[0]))
	target = quad(target_quad, (w, h))
	if cv2.contourArea(source, oriented=True) * cv2.contourArea(target, oriented=True) <= 0:
		raise PreservationError("Source and target corner order would mirror the artwork.")
	alpha = (
		artwork[:, :, 3].astype(np.float32) / 255
		if artwork.shape[2] == 4
		else np.ones(artwork.shape[:2], np.float32)
	)
	mask = np.zeros(artwork.shape[:2], np.uint8)
	cv2.fillConvexPoly(mask, source.astype(np.int32), 1)
	alpha *= mask
	if not np.any(alpha):
		raise PreservationError("Artwork plane is completely transparent.")
	matrix = cv2.getPerspectiveTransform(source, target)
	paint = cv2.warpPerspective(artwork[:, :, :3], matrix, (w, h))
	opacity = cv2.warpPerspective(alpha, matrix, (w, h))
	from joymedia.services.consistency.surfaces import blend_surface

	return blend_surface(background, paint, opacity, mode=blend_mode)


@frappe.whitelist(methods=["POST"])
def repair_opening_art(project_name, shot_name, expected_frame, planes):
	import cv2
	import numpy as np

	from joymedia.api.storyboard import _busy_shots
	from joymedia.services.consistency.repair import _project_asset_path

	project, shot, _url, content, token = _opening(project_name, shot_name)
	project._require_write_access()
	if token != frappe.parse_json(expected_frame):
		frappe.throw("The opening image changed. Reload before repairing it.")
	if shot.name in _busy_shots(project.name):
		frappe.throw("Wait for this scene's render to finish.")
	planes = frappe.parse_json(planes) if isinstance(planes, str) else planes
	if not isinstance(planes, list) or not 1 <= len(planes) <= 8:
		frappe.throw("Supply one to eight printed surfaces.")
	image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
	evidence = []
	for plane in planes:
		if (
			not isinstance(plane, dict)
			or not {"artwork", "source_quad", "target_quad"} <= set(plane)
			or set(plane) - {"artwork", "source_quad", "target_quad", "blend_mode"}
		):
			frappe.throw("Each surface needs artwork and matching source/target quadrilaterals.")
		path = _project_asset_path(project, plane["artwork"])
		art = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
		image = project_surface(
			image,
			art,
			plane["source_quad"],
			plane["target_quad"],
			blend_mode=plane.get("blend_mode", "source"),
		)
		evidence.append({**plane, "artwork_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
	ok, data = cv2.imencode(".png", image)
	if not ok:
		frappe.throw("Could not encode the repaired image.")
	# A candidate does not replace or approve the current opening.
	asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"media_project": project.name,
			"asset_name": f"{shot.name} opening artwork repair",
			"media_type": "Image",
			"asset_category": "Reference",
			"asset_scope": "Project Output",
			"status": "Active",
		}
	).insert(ignore_permissions=True)
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{shot.name}-source-art-{frappe.generate_hash(length=8)}.png",
			"content": data.tobytes(),
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": asset.name,
		}
	).insert(ignore_permissions=True)
	version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": asset.name,
			"file": file.file_url,
			"source": "Composed",
			"derived_from": token.get("asset_version"),
			"analysis_json": json.dumps(
				{
					"opening_art_repair": {
						"shot": shot.name,
						"source": token,
						"planes": evidence,
						"strategy": "opencv_source_surface_projection",
						"scope": "Projected printed surfaces only; geometry, support, occlusion and visual quality require review.",
					}
				}
			),
		}
	).insert(ignore_permissions=True)
	return {"asset_version": version.name, "file": file.file_url, "expected_frame": token}


@frappe.whitelist(methods=["POST"])
def use_opening_art_repair(project_name, shot_name, asset_version, expected_frame):
	from joymedia.api.storyboard import set_project_shot_keyframe
	from joymedia.services.consistency.repair import _project_asset_path

	project, shot, _url, _content, token = _opening(project_name, shot_name)
	project._require_write_access()
	if token != frappe.parse_json(expected_frame):
		frappe.throw("The opening image changed. Review the new image first.")
	_project_asset_path(project, asset_version)
	version = frappe.get_doc("Asset Version", asset_version)
	proof = (frappe.parse_json(version.analysis_json or "{}") or {}).get("opening_art_repair") or {}
	if proof.get("shot") != shot.name or proof.get("source") != token:
		frappe.throw("This repair candidate belongs to another opening image.")
	return set_project_shot_keyframe(project.name, shot.name, "first_frame", version.name)
