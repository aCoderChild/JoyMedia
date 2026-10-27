"""Measured, reviewable product placement on one immutable opening background."""

import hashlib
import io
import math

import frappe


def projected_product_box(canvas_size, source_size, placement):
	"""Size a cutout against a measured tabletop quadrilateral at its depth.

	``table_quad`` is back-left, back-right, front-right, front-left in
	normalized image coordinates. ``anchor`` is the product's bottom centre in
	rectified table coordinates. Scale comes from measured product/support
	widths when available; otherwise the caller supplies an estimated
	``width_fraction`` for explicit review.
	"""
	import cv2
	import numpy as np

	if (
		not isinstance(placement, dict)
		or not {"table_quad", "anchor"} <= set(placement)
		or set(placement) - {"table_quad", "anchor", "width_fraction", "scale_evidence"}
	):
		raise ValueError("Placement needs a table quad, anchor and scale evidence or width fraction.")
	quad, anchor = placement["table_quad"], placement["anchor"]
	evidence = placement.get("scale_evidence")
	if "width_fraction" not in placement and not evidence:
		raise ValueError("Placement needs physical measurements or a reviewed width fraction.")
	ratio = placement.get("width_fraction")
	if (
		not isinstance(quad, list)
		or len(quad) != 4
		or any(
			not isinstance(p, list)
			or len(p) != 2
			or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in p)
			for p in quad
		)
	):
		raise ValueError("Table quad needs four normalized corners in back-to-front order.")
	if (
		not isinstance(anchor, list)
		or len(anchor) != 2
		or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in anchor)
	):
		raise ValueError("Anchor needs two normalized table coordinates.")
	if evidence is not None:
		if not isinstance(evidence, dict) or set(evidence) != {"product_width_mm", "support_width_mm"}:
			raise ValueError("Scale evidence needs product and support widths in millimetres.")
		product_mm, support_mm = evidence["product_width_mm"], evidence["support_width_mm"]
		if any(
			type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (product_mm, support_mm)
		):
			raise ValueError("Measured widths must be positive and finite.")
		measured_ratio = product_mm / support_mm
		if ratio is None:
			ratio = measured_ratio
		elif (
			type(ratio) not in (int, float)
			or not math.isfinite(ratio)
			or not math.isclose(measured_ratio, ratio, rel_tol=0.02)
		):
			raise ValueError("Width fraction conflicts with the supplied physical measurements.")
	if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 < ratio < 1:
		raise ValueError("Width fraction must be between zero and one.")
	if anchor[0] - ratio / 2 < 0 or anchor[0] + ratio / 2 > 1:
		raise ValueError("Product width extends beyond the table.")
	cw, ch = canvas_size
	pixels = np.asarray(quad, np.float32) * np.asarray([cw, ch], np.float32)
	if not cv2.isContourConvex(pixels) or cv2.contourArea(pixels) < 100:
		raise ValueError("Table quad must be convex and ordered around a visible surface.")
	unit = np.asarray([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
	transform = cv2.getPerspectiveTransform(unit, pixels.astype(np.float32))
	u, v = anchor
	points = cv2.perspectiveTransform(
		np.asarray([[[u - ratio / 2, v], [u + ratio / 2, v], [u, v]]], np.float32), transform
	)[0]
	left, right, bottom = points
	width = round(float(np.linalg.norm(right - left)))
	height = round(width * source_size[1] / source_size[0])
	x, y = round(float(bottom[0]) - width / 2), round(float(bottom[1]) - height)
	if min(width, height) < 16 or x < 0 or y < 0 or x + width > cw or y + height > ch:
		raise ValueError("Projected product does not fit the background frame.")
	return (x, y, width, height), {
		"kind": "table_projective_scale",
		"table_quad": quad,
		"anchor": anchor,
		"width_fraction": ratio,
		"projected_footprint": points.tolist(),
		"scale_evidence": evidence,
		"scope": "Camera-plane scale estimate; product thickness, occlusion and physical dimensions still need review.",
	}


def compose_product_on_surface(background_bytes, cutout_bytes, box, surface):
	"""Return a candidate frame and 2D support evidence; never infer 3D fit."""
	import numpy as np
	from PIL import Image, ImageDraw, ImageFilter

	from joymedia.services.scene.artwork import fit_box, validate_surface_contact

	with Image.open(io.BytesIO(background_bytes)) as image:
		background = image.convert("RGBA")
	with Image.open(io.BytesIO(cutout_bytes)) as image:
		if image.mode != "RGBA":
			raise ValueError("Product placement requires a transparent RGBA cutout.")
		source = image.copy()
	if source.getchannel("A").getextrema() != (0, 255):
		raise ValueError("Product cutout needs both transparent background and opaque product pixels.")
	visible = source.getchannel("A").point(lambda alpha: 255 if alpha > 8 else 0).getbbox()
	if not visible:
		raise ValueError("Product cutout has no visible pixels.")
	source = source.crop(visible)
	geometry = None
	if surface.get("placement"):
		(x, y, width, height), geometry = projected_product_box(
			background.size, source.size, surface["placement"]
		)
	else:
		x, y, width, height = fit_box(background.size, source.size, box)
	if min(width, height) < 16:
		raise ValueError("Product placement is too small for useful review.")
	proof = validate_surface_contact(
		background_bytes,
		background.size,
		source,
		(x, y, width, height),
		{"background_sha256": surface["background_sha256"], "polygon": surface["polygon"]},
	)
	if geometry:
		import numpy as np

		contacts = np.asarray(proof["contact_points"], dtype=np.float64)
		expected = geometry["projected_footprint"]
		table_slope = (expected[1][1] - expected[0][1]) / (expected[1][0] - expected[0][0])
		cutout_slope = float(np.polyfit(contacts[:, 0], contacts[:, 1], 1)[0])
		deviation = abs(math.degrees(math.atan(cutout_slope) - math.atan(table_slope)))
		geometry["footprint_angle_error_degrees"] = round(deviation, 2)
		geometry["perspective_warning"] = deviation > 8
	scaled = source.resize((width, height), Image.Resampling.LANCZOS)
	tabletop = Image.new("L", background.size, 0)
	ImageDraw.Draw(tabletop).polygon(
		[(round(u * background.width), round(v * background.height)) for u, v in surface["polygon"]], fill=255
	)
	# Adapt only low-frequency room illumination. The source view remains
	# available unchanged; this rendered candidate deliberately changes RGB
	# slightly so cool studio whites do not glow in a warm room.
	table_pixels = np.asarray(background.convert("RGB"), dtype=np.float32)[np.asarray(tabletop) > 0]
	if len(table_pixels):
		ambient = np.median(table_pixels, axis=0)
		chroma = np.clip(ambient / max(1.0, float(ambient.mean())), 0.8, 1.2)
		gains = np.clip((0.72 + 0.28 * chroma) * 0.96, 0.84, 1.05)
		# Carry the table's broad light falloff across the pack. Limit the
		# adjustment so supplied package colours and printed art stay legible.
		room_light = np.asarray(
			background.crop((x, y, x + width, y + height))
			.convert("L")
			.filter(ImageFilter.GaussianBlur(max(8, width // 4))),
			dtype=np.float32,
		)
		local_gain = np.clip(room_light / max(1.0, float(np.median(room_light))), 0.90, 1.08)
		rgba = np.asarray(scaled, dtype=np.float32).copy()
		rgba[:, :, :3] = np.clip(rgba[:, :, :3] * gains * local_gain[:, :, None], 0, 255)
		scaled = Image.fromarray(rgba.astype(np.uint8), "RGBA")
	# A 3D pack casts a shadow from its contact contour toward the room's
	# darker side. Keep both the tight and diffuse shadow on the measured table.
	alpha = np.asarray(scaled.getchannel("A"))
	baseline = []
	for column in range(0, width, max(1, width // 96)):
		visible = np.flatnonzero(alpha[:, column] >= 200)
		if len(visible):
			baseline.append((x + column, y + int(visible[-1])))
	shadow = Image.new("L", background.size, 0)
	if len(baseline) >= 2:
		draw = ImageDraw.Draw(shadow)
		offset = max(2, round(height * 0.035))
		shifted = [(px + offset, py + offset) for px, py in baseline]
		draw.line(shifted, fill=125, width=max(3, round(height * 0.035)), joint="curve")
		diffuse = shadow.filter(ImageFilter.GaussianBlur(max(3, height * 0.045)))
		tight = shadow.filter(ImageFilter.GaussianBlur(max(1, height * 0.012)))
		shadow = Image.blend(diffuse, tight, 0.52)
		shadow = Image.fromarray(
			np.minimum(np.asarray(shadow, dtype=np.uint16), np.asarray(tabletop, dtype=np.uint16)).astype(
				np.uint8
			),
			"L",
		)
		background.paste(Image.new("RGBA", background.size, (35, 28, 25, 255)), (0, 0), shadow)
	background.alpha_composite(scaled, (x, y))
	output = io.BytesIO()
	background.convert("RGB").save(output, "PNG")
	return output.getvalue(), {
		**proof,
		"box_pixels": [x, y, width, height],
		**({"geometry": geometry} if geometry else {}),
		"rendering": "ambient_chroma_local_light_and_contact_shadow_v3",
	}


@frappe.whitelist(methods=["POST"])
def prepare_product_first_frame(
	project_name,
	shot_name,
	background_asset_version,
	cutout_asset_version,
	box=None,
	support_polygon=None,
	placement=None,
):
	"""Create a private candidate for human review; leave the live first frame intact."""
	from joymedia.services.consistency.repair import _project_asset_path

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw("Shot does not belong to this project.", frappe.PermissionError)
	selected = {row.asset_version: row for row in project.selected_media or []}
	background_row = selected.get(background_asset_version)
	product_row = selected.get(cutout_asset_version)
	if not background_row or background_row.reference_role not in {"Environment", "Background"}:
		raise ValueError("Choose a selected project background.")
	if not product_row or product_row.reference_role != "Product":
		raise ValueError("Choose a selected project product cutout.")
	version = frappe.get_doc("Asset Version", cutout_asset_version)
	analysis = frappe.parse_json(version.analysis_json or "{}") or {}
	if analysis.get("product_view_status") != "operator_masked_view_unverified":
		raise ValueError("Product must be a reviewed transparent cutout from a supplied view.")
	box = frappe.parse_json(box) if isinstance(box, str) else box
	polygon = frappe.parse_json(support_polygon) if isinstance(support_polygon, str) else support_polygon
	placement = frappe.parse_json(placement) if isinstance(placement, str) else placement
	if placement is None:
		raise ValueError("Product placement needs table-relative scale and perspective evidence.")
	if polygon is None:
		polygon = placement.get("table_quad") if isinstance(placement, dict) else None
	if box is not None:
		# A legacy authored box may be retained for provenance, but the
		# projective placement—not this box—determines the rendered size.
		from joymedia.services.scene.artwork import placements

		placements({"artwork_placements": [{"asset_version": cutout_asset_version, "box": box}]})
	background_bytes = _project_asset_path(project, background_asset_version).read_bytes()
	cutout_bytes = _project_asset_path(project, cutout_asset_version).read_bytes()
	surface = {"background_sha256": hashlib.sha256(background_bytes).hexdigest(), "polygon": polygon}
	if placement is not None:
		surface["placement"] = placement
	content, proof = compose_product_on_surface(background_bytes, cutout_bytes, box, surface)
	asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"media_project": project.name,
			"asset_name": f"{shot.name} measured product first-frame candidate",
			"media_type": "Image",
			"asset_category": "Reference",
			"asset_scope": "Project Output",
			"status": "Active",
		}
	).insert(ignore_permissions=True)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{shot.name}-product-placement-{frappe.generate_hash(length=8)}.png",
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": asset.name,
		}
	).insert(ignore_permissions=True)
	provenance = {
		"shot": shot.name,
		"background_asset_version": background_asset_version,
		"product_asset_version": cutout_asset_version,
		"product_view": product_row.product_view,
		"background_sha256": surface["background_sha256"],
		"product_sha256": hashlib.sha256(cutout_bytes).hexdigest(),
		"candidate_sha256": hashlib.sha256(content).hexdigest(),
		"validation_schema": 2,
		"box": box,
		"surface": surface,
		"contact": proof,
		"scope": "Perspective-scaled tabletop candidate with room-light adaptation when placement evidence is supplied; pack dimensions, occlusion, print and script fit need human review.",
	}
	candidate = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": asset.name,
			"file": file_doc.file_url,
			"source": "Composed",
			"derived_from": background_asset_version,
			"analysis_json": frappe.as_json({"product_first_frame_candidate": provenance}),
		}
	).insert(ignore_permissions=True)
	return {"asset_version": candidate.name, "file": file_doc.file_url, "proof": provenance}


@frappe.whitelist(methods=["POST"])
def use_product_first_frame(project_name, shot_name, candidate_asset_version):
	"""Promote only a candidate whose exact source background is still present."""
	from joymedia.api.storyboard import set_project_shot_keyframe
	from joymedia.services.consistency.repair import _project_asset_path
	from joymedia.services.planning.durations import ensure_shot_planning_editable

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw("Shot does not belong to this project.", frappe.PermissionError)
	candidate_path = _project_asset_path(project, candidate_asset_version)
	candidate = frappe.get_doc("Asset Version", candidate_asset_version)
	proof = (frappe.parse_json(candidate.analysis_json or "{}") or {}).get(
		"product_first_frame_candidate"
	) or {}
	if proof.get("shot") != shot.name:
		raise ValueError("This placement candidate belongs to another shot.")
	if proof.get("validation_schema") != 2 or not proof.get("contact", {}).get("geometry"):
		raise ValueError("This placement has no current perspective and scale proof; prepare it again.")
	if hashlib.sha256(candidate_path.read_bytes()).hexdigest() != proof.get("candidate_sha256"):
		raise ValueError("The composed candidate changed; prepare it again.")
	selected = {row.asset_version for row in project.selected_media or []}
	if {proof.get("background_asset_version"), proof.get("product_asset_version")} - selected:
		raise ValueError("The candidate's product or background is no longer selected.")
	background = _project_asset_path(project, proof["background_asset_version"]).read_bytes()
	product = _project_asset_path(project, proof["product_asset_version"]).read_bytes()
	if hashlib.sha256(product).hexdigest() != proof.get("product_sha256"):
		raise ValueError("The product cutout changed; prepare a new candidate.")
	if hashlib.sha256(background).hexdigest() != proof.get("background_sha256"):
		raise ValueError("The source background changed; prepare a new candidate.")
	ensure_shot_planning_editable(project.name)
	# Keep the same exact view as the product reference used by subsequent
	# rendering; otherwise the first frame and generation input contradict.
	inputs = [
		{"reference_role": row.reference_role, "asset_version": row.asset_version}
		for row in shot.generation_inputs or []
		if frappe.scrub(row.reference_role or "") != "product"
	]
	inputs.append({"reference_role": "Product", "asset_version": proof["product_asset_version"]})
	shot.set("generation_inputs", inputs)
	shot.consistency_status = "Needs Review"
	if proof.get("contact", {}).get("geometry"):
		shot.consistency_notes = (
			"Table-relative perspective sizing and 2D contact passed. The supplied width ratio is "
			"an estimate; review real pack dimensions, cutout perspective, occlusion, print, and "
			"storyboard fit before rendering video."
		)
	else:
		shot.consistency_notes = (
			"Measured product contact passed a 2D tabletop check. Review the new first frame for "
			"pack perspective, scale, occlusion, print, and storyboard fit before rendering video."
		)
	shot.save(ignore_permissions=True)
	return set_project_shot_keyframe(project.name, shot.name, "first_frame", candidate.name)
