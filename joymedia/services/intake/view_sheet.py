"""Split a character turnaround sheet into one reference image per view.

A sheet shows the same character several times side by side (front, three-quarter,
side, back) on a plain backdrop. Given to the picture model as one reference, it
draws the character twice, e.g. a front view at the table and the back view on
the floor. Each view becomes its own reference of the same identity, so scene
planning picks the one view a shot needs (services/scene/references.py).
"""

import io
import re

import frappe
import numpy as np

VIEW_QUESTION = (
	"This picture shows one character. Which side of it faces the viewer? "
	'Return JSON {"view": "front", "three-quarter front", "side" or "back"}.'
)
VIEW_SUFFIX = re.compile(r"_view\d+$")


def _runs(flags, min_gap):
	"""Contiguous True runs of a 1-D mask as (start, end), joining gaps shorter than ``min_gap``."""
	runs, start = [], None
	for index, value in enumerate(flags):
		if value and start is None:
			start = index
		elif not value and start is not None:
			runs.append([start, index])
			start = None
	if start is not None:
		runs.append([start, len(flags)])
	merged = []
	for run in runs:
		if merged and run[0] - merged[-1][1] < min_gap:
			merged[-1][1] = run[1]
		else:
			merged.append(run)
	return merged


def split_view_sheet(data):
	"""PNG crops of each view when ``data`` is a side-by-side character sheet, else []."""
	from PIL import Image

	image = Image.open(io.BytesIO(data)).convert("RGB")
	pixels = np.asarray(image).astype(int)
	height, width = pixels.shape[:2]
	if width < height * 1.3:
		return []
	border = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
	if np.std(border, axis=0).max() > 18:
		return []  # not a plain backdrop: a photo, not a sheet
	foreground = np.abs(pixels - np.median(border, axis=0)).sum(axis=2) > 45
	columns = _runs(foreground.sum(axis=0) > height * 0.02, max(2, int(width * 0.01)))
	columns = [run for run in columns if run[1] - run[0] >= width * 0.06]
	if not 2 <= len(columns) <= 8:
		return []
	figures = []
	for left, right in columns:
		rows = _runs(
			foreground[:, left:right].sum(axis=1) > (right - left) * 0.02, max(2, int(height * 0.01))
		)
		top, bottom = max(rows, key=lambda run: run[1] - run[0])  # the figure, not its caption
		figures.append((left, right, top, bottom))
	tallest = max(bottom - top for _left, _right, top, bottom in figures)
	if any(bottom - top < max(tallest / 1.5, height * 0.25) for _left, _right, top, bottom in figures):
		return []  # unequal subjects: a group picture, not views of one character
	crops = []
	for index, (left, right, top, bottom) in enumerate(figures):
		pad = int(tallest * 0.08)
		# Pad at most halfway to a neighbouring view, so no sliver of it is cropped in.
		low = (figures[index - 1][1] + left) // 2 if index else 0
		high = (right + figures[index + 1][0]) // 2 if index + 1 < len(figures) else width
		box = (max(low, left - pad), max(0, top - pad), min(high, right + pad), min(height, bottom + pad))
		output = io.BytesIO()
		image.crop(box).save(output, "PNG")
		crops.append(output.getvalue())
	return crops


def _view_name(crop, index):
	from joymedia.services.review.consistency import ask

	try:
		view = str(ask(crop, VIEW_QUESTION).get("view") or "").strip().lower()
	except Exception:
		view = ""
	return view if view in {"front", "three-quarter front", "side", "back"} else f"view {index}"


def split_project_view_sheets(project_name):
	"""Replace each character sheet among the project's references with its separate views. Idempotent."""
	from frappe.utils.file_manager import save_file

	from joymedia.services.intake.assets import create_media_asset
	from joymedia.services.scene.references import identity_key

	project = frappe.get_doc("Media Project", project_name)
	split = []
	for row in list(project.selected_media or []):
		if row.reference_role not in {"Character", "Person"} or VIEW_SUFFIX.search(row.reference_key or ""):
			continue
		version = frappe.db.get_value(
			"Asset Version", row.asset_version, ["file", "media_asset"], as_dict=True
		)
		if not version or not version.file:
			continue
		try:
			crops = split_view_sheet(frappe.get_doc("File", {"file_url": version.file}).get_content())
		except Exception:
			continue
		if not crops:
			continue
		identity = identity_key(row) or row.reference_key
		category = frappe.db.get_value("Media Asset", version.media_asset, "asset_category")
		# "Gấu Shera (round cream body, ...)" -> "Gấu Shera"; the description stays on the original.
		label = (row.label or row.reference_key or "Character").split(" (")[0].strip()[:80]
		stem = frappe.scrub(row.reference_key or "character")
		for index, crop in enumerate(crops, start=1):
			view = _view_name(crop, index)
			file_doc = save_file(
				f"{stem}-{frappe.scrub(view)}.png",
				crop,
				"Media Project",
				project.name,
				is_private=1,
			)
			asset = create_media_asset(f"{label} {view}", category, file_url=file_doc.file_url)
			project.append(
				"selected_media",
				{
					"asset_version": asset["asset_version"],
					"reference_key": f"{stem}_view{index}",
					"identity_key": identity,
					"reference_role": row.reference_role,
					"label": f"{label} {view}",
					"relative_size": row.relative_size,
					"keep_rule": row.keep_rule,
					"motion_reference_use": row.motion_reference_use,
				},
			)
		project.set("selected_media", [item for item in project.selected_media if item is not row])
		split.append(row.asset_version)
	if split:
		project.save(ignore_permissions=True)
	return split
