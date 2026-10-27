"""Register explicitly cropped product-sheet views as separate white-background references.

The crop boxes and angle names are supplied by an operator after inspecting the
sheet. No view is inferred from pixels, and no hidden package panel is invented.
"""

from __future__ import annotations

import io

import frappe

ALLOWED_VIEWS = {"front", "front_left", "front_right", "top_front", "left", "right", "side", "back"}


def white_background_crop(image, box, size=1024):
	"""Keep the supplied pixels at native scale on a square pure-white canvas."""
	from PIL import Image

	if not isinstance(box, (list, tuple)) or len(box) != 4 or any(type(v) is not int for v in box):
		raise ValueError("A product-view crop needs four integer pixel coordinates.")
	left, top, right, bottom = box
	if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
		raise ValueError("Product-view crop exceeds the source sheet.")
	crop = image.convert("RGB").crop(box)
	edge = max(size, crop.width + 64, crop.height + 64)
	canvas = Image.new("RGB", (edge, edge), "white")
	canvas.paste(crop, ((edge - crop.width) // 2, (edge - crop.height) // 2))
	output = io.BytesIO()
	canvas.save(output, "PNG")
	return output.getvalue()


def transparent_product_cutout(image, outline, margin=12):
	"""Mask a reviewed outline without repainting any package pixel.

	The caller supplies the visible silhouette in source-image pixel coordinates.
	A white studio canvas is never interpreted as transparency automatically:
	white packaging faces would otherwise be erased with the background.
	"""
	from PIL import Image, ImageDraw

	if (
		not isinstance(outline, (list, tuple))
		or not 4 <= len(outline) <= 24
		or any(
			not isinstance(point, (list, tuple))
			or len(point) != 2
			or any(type(value) is not int for value in point)
			for point in outline
		)
	):
		raise ValueError("A product cutout needs 4–24 reviewed pixel points.")
	if any(not (0 <= x < image.width and 0 <= y < image.height) for x, y in outline):
		raise ValueError("Product outline exceeds the source image.")
	left = max(0, min(x for x, _ in outline) - margin)
	top = max(0, min(y for _, y in outline) - margin)
	right = min(image.width, max(x for x, _ in outline) + margin + 1)
	bottom = min(image.height, max(y for _, y in outline) + margin + 1)
	# Supersampling softens the silhouette by less than a source pixel. The
	# interior RGB remains byte-for-byte from the selected source view.
	factor = 4
	mask = Image.new("L", ((right - left) * factor, (bottom - top) * factor), 0)
	ImageDraw.Draw(mask).polygon([((x - left) * factor, (y - top) * factor) for x, y in outline], fill=255)
	mask = mask.resize((right - left, bottom - top), Image.Resampling.LANCZOS)
	cutout = image.convert("RGBA").crop((left, top, right, bottom))
	cutout.putalpha(mask)
	output = io.BytesIO()
	cutout.save(output, "PNG")
	return output.getvalue()


@frappe.whitelist(methods=["POST"])
def add_reviewed_product_cutout(project_name, source_key, outline):
	"""Publish an operator-masked view without changing the supplied RGB artwork."""
	import hashlib

	from frappe.utils.file_manager import save_file
	from PIL import Image

	from joymedia.services.consistency.repair import _project_asset_path
	from joymedia.services.intake.assets import create_media_asset
	from joymedia.services.scene.references import identity_key

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	source = next((row for row in project.selected_media or [] if row.reference_key == source_key), None)
	if not source or source.reference_role != "Product":
		raise ValueError("Choose a selected product view in this project.")
	outline = frappe.parse_json(outline) if isinstance(outline, str) else outline
	source_path = _project_asset_path(project, source.asset_version)
	with Image.open(source_path) as image:
		content = transparent_product_cutout(image, outline)
	digest = hashlib.sha256(content).hexdigest()[:12]
	key = f"{source_key}_cutout_{digest}"
	existing = next((row for row in project.selected_media or [] if row.reference_key == key), None)
	if existing:
		return {"reference_key": key, "asset_version": existing.asset_version, "reused": True}
	view = source.product_view or "source"
	upload = save_file(f"{key}.png", content, "Media Project", project.name, is_private=1)
	asset = create_media_asset(
		f"{source.label or source_key} transparent cutout", "Product", file_name=upload.name
	)
	frappe.db.set_value(
		"Asset Version",
		asset["asset_version"],
		{
			"source": "Preprocessed",
			"derived_from": source.asset_version,
			"analysis_status": "Ready",
			"analysis_json": frappe.as_json(
				{
					"kind": "product",
					"product_view": view,
					"product_view_status": "operator_masked_view_unverified",
					"source_asset_version": source.asset_version,
					"source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
					"outline": outline,
					"scope": "Exact source RGB inside a reviewed silhouette; perspective and occlusion require review.",
				}
			),
		},
		update_modified=False,
	)
	frappe.db.set_value(
		"File",
		upload.name,
		{
			"attached_to_doctype": "Media Project",
			"attached_to_name": project.name,
		},
		update_modified=False,
	)
	project.append(
		"selected_media",
		{
			"asset_version": asset["asset_version"],
			"reference_key": key,
			"identity_key": identity_key(source),
			"reference_role": "Product",
			"product_view": view,
			"label": f"{source.label or source_key} · transparent cutout",
			"relative_size": source.relative_size,
			"keep_rule": source.keep_rule,
		},
	)
	project.save(ignore_permissions=True)
	return {"reference_key": key, "asset_version": asset["asset_version"], "reused": False}


def add_product_sheet_views(project_name, source_key, sheet_asset_version, view_boxes):
	"""Add inspected views to one project; reruns skip references already added.

	``view_boxes`` maps view names to [left, top, right, bottom] source pixels.
	This deliberately requires declared boxes because automated splitting of a
	labelled multi-row sheet can include captions or neighboring products.
	"""
	from frappe.utils.file_manager import save_file
	from PIL import Image

	from joymedia.services.intake.assets import create_media_asset
	from joymedia.services.scene.references import identity_key

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	source = next((row for row in project.selected_media or [] if row.reference_key == source_key), None)
	if not source or source.reference_role != "Product":
		raise ValueError("Source reference must be a selected Product in this project.")
	if not isinstance(view_boxes, dict) or not view_boxes or len(view_boxes) > 8:
		raise ValueError("Supply one to eight labelled product-view crops.")
	if set(view_boxes) - ALLOWED_VIEWS:
		raise ValueError("Unsupported product-view label.")
	sheet = frappe.get_doc("Asset Version", sheet_asset_version)
	sheet.check_permission("read")
	file_doc = frappe.get_doc("File", {"file_url": sheet.file})
	file_doc.check_permission("read")
	with Image.open(file_doc.get_full_path()) as original:
		image = original.convert("RGB")

	identity = identity_key(source)
	added = []
	for view, box in view_boxes.items():
		key = f"{source_key}_{view}"
		if any(row.reference_key == key for row in project.selected_media or []):
			continue
		content = white_background_crop(image, box)
		file_doc = save_file(f"{key}-white.png", content, "Media Project", project.name, is_private=1)
		asset = create_media_asset(
			f"{source.label or source_key} {view} (sheet crop)", "Product", file_name=file_doc.name
		)
		frappe.db.set_value(
			"Asset Version",
			asset["asset_version"],
			{
				"analysis_status": "Ready",
				"analysis_json": frappe.as_json(
					{
						"kind": "product",
						"product_view": view,
						"product_view_status": "supplied_sheet_crop_unverified",
						"source_asset_version": sheet.name,
						"unknown_panels": "not shown in supplied sheet; unverified",
					}
				),
			},
			update_modified=False,
		)
		# The project's owner must be able to view these private inputs from
		# their video workspace, independent of Media Asset library permissions.
		frappe.db.set_value(
			"File",
			file_doc.name,
			{
				"attached_to_doctype": "Media Project",
				"attached_to_name": project.name,
			},
			update_modified=False,
		)
		project.append(
			"selected_media",
			{
				"asset_version": asset["asset_version"],
				"reference_key": key,
				"identity_key": identity,
				"reference_role": "Product",
				"product_view": view,
				"label": f"{source.label or source_key} · {view.replace('_', ' ')} (sheet crop)",
				"relative_size": source.relative_size,
				"keep_rule": source.keep_rule,
			},
		)
		added.append({"view": view, "reference_key": key, "asset_version": asset["asset_version"]})
	if added:
		project.save(ignore_permissions=True)
	return added
