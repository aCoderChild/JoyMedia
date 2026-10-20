"""Authored source-art positions, independent of subject, model and resolution."""

import json
import math


def placements(plan):
	if isinstance(plan, str):
		plan = json.loads(plan) if plan.strip() else {}
	rows = plan.get("artwork_placements", []) if isinstance(plan, dict) else []
	if not isinstance(rows, list) or len(rows) > 8:
		raise ValueError("Supply at most eight artwork placements.")
	result, seen = [], set()
	for row in rows:
		if not isinstance(row, dict) or (
			set(row) - {"asset_version", "box", "entity", "support_surface"}
			or not {"asset_version", "box"} <= set(row)
		):
			raise ValueError("Artwork placements require an asset version and normalized box.")
		version, box = row["asset_version"], row["box"]
		if not isinstance(version, str) or not version.strip() or version in seen:
			raise ValueError("Each artwork placement needs a unique asset version.")
		if (
			not isinstance(box, list)
			or len(box) != 4
			or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
		):
			raise ValueError("Artwork boxes need four finite normalized coordinates.")
		x, y, w, h = box
		if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
			raise ValueError("Artwork boxes must fit inside the image.")
		seen.add(version)
		entity = row.get("entity")
		if entity is not None:
			from joymedia.services.scene.contract import read_contract

			contract = read_contract(plan)
			known = {item["id"] for item in (contract or {}).get("entities", [])}
			if not isinstance(entity, str) or entity not in known:
				raise ValueError("Placed artwork must name a declared scene entity.")
		result.append(
			{
				"asset_version": version,
				"box": list(box),
				**({"entity": entity} if entity else {}),
				**({"support_surface": row["support_surface"]} if "support_surface" in row else {}),
			}
		)
	return result


def fit_box(canvas, source, box):
	"""Fit unwarped artwork inside its authored area, grounded at its bottom."""
	cw, ch = canvas
	sw, sh = source
	x, y, w, h = box
	scale = min(cw * w / sw, ch * h / sh)
	width, height = max(1, round(sw * scale)), max(1, round(sh * scale))
	return round(cw * (x + w / 2) - width / 2), round(ch * (y + h) - height), width, height


def validate_surface_contact(background_bytes, canvas_size, asset, box, surface):
	"""Reject unsupported 2D placement; this necessary test is not 3D certification.

	The visible supporting region is tied to the exact uncomposited frame. Use
	OpenCV's existing polygon primitive rather than treating a bounding rectangle
	or an added shadow as evidence of contact.
	"""
	import hashlib

	import cv2
	import numpy as np

	if not isinstance(surface, dict) or set(surface) != {"background_sha256", "polygon"}:
		raise ValueError("Product placement needs a supporting surface tied to this frame.")
	if surface["background_sha256"] != hashlib.sha256(background_bytes).hexdigest():
		raise ValueError("Supporting surface belongs to a different frame.")
	points = surface["polygon"]
	if (
		not isinstance(points, list)
		or not 3 <= len(points) <= 8
		or any(
			not isinstance(p, list)
			or len(p) != 2
			or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in p)
			for p in points
		)
	):
		raise ValueError("Supporting surface needs 3–8 finite normalized vertices.")
	polygon = np.asarray(points, dtype=np.float32) * np.asarray(canvas_size, dtype=np.float32)
	if not cv2.isContourConvex(polygon) or abs(cv2.contourArea(polygon)) < 4:
		raise ValueError("Supporting surface must be a nonempty convex region.")
	x, y, width, height = box
	alpha = np.asarray(asset.getchannel("A").resize((width, height)))
	contact = []
	for fraction in (0.1, 0.25, 0.5, 0.75, 0.9):
		column = min(width - 1, round((width - 1) * fraction))
		visible = np.flatnonzero(alpha[:, column] >= 254)
		if not len(visible):
			continue
		point = (float(x + column), float(y + visible[-1]))
		if cv2.pointPolygonTest(polygon, point, False) < 0:
			raise ValueError(
				"Product contact footprint lies outside its supporting surface; do not paste a floating object."
			)
		contact.append(list(point))
	if len(contact) < 3:
		raise ValueError("Product has insufficient visible contact evidence.")
	return {
		"kind": "surface_contact_2d",
		"background_sha256": surface["background_sha256"],
		"polygon": points,
		"contact_points": contact,
		"scope": "2D containment only; scale, perspective and occlusion require review",
	}
