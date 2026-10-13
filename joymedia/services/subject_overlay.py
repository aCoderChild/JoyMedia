"""Exact reproduction of the real mascot, product and logo images in a keyframe.

An image model can only imitate a reference: proportions drift, claws blur, lettering turns to nonsense.
So a reference that is a transparent cutout (a Character, Product or Logo) is not given to the image model
at all. The model draws only the empty setting, and the real pixels are pasted over it afterwards with one
uniform scale factor, which keeps the asset's aspect ratio and every detail. A reference without
transparency cannot be pasted and still guides the image model as before.
"""

import io
from functools import lru_cache
from pathlib import Path

import frappe

PASTE_ROLES = frozenset({"character", "product", "logo"})
# Fractions of the canvas height, except logos which are bounded by both width and height.
SUBJECT_HEIGHT = {"character": 0.62, "product": 0.40}
BASELINE = 0.94
SPACING_MARGIN = 0.90
LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT, LOGO_MARGIN = 0.22, 0.08, 0.04
OPAQUE_BELOW = 250

EMPTY_SETTING = (
	"Show only the empty setting, with clear open floor or table space in the lower middle of the frame. "
	"Do not draw any character, mascot, animal, product, packaging, logo or text."
)


def _role(reference):
	role = frappe.scrub(reference.get("reference_role") or reference.get("input_role") or "")
	# Workflow routing names a character's role "person".
	return "character" if role in ("person", "people", "talent") else role


@lru_cache(maxsize=256)
def _cutout_path(asset_version):
	"""Full path of an Asset Version's image when it has real transparency, else None."""
	from PIL import Image

	file_url = frappe.db.get_value("Asset Version", asset_version, "file")
	if not file_url:
		return None
	path = Path(frappe.get_doc("File", {"file_url": file_url}).get_full_path())
	try:
		with Image.open(path) as image:
			if image.mode not in ("RGBA", "LA", "P") and "transparency" not in image.info:
				return None
			if image.convert("RGBA").getchannel("A").getextrema()[0] >= OPAQUE_BELOW:
				return None
	except OSError:
		return None
	return str(path)


def pasted_references(references):
	"""The references that are pasted rather than shown to the image model, in the given order."""
	pasted = []
	for reference in references or []:
		asset_version = reference.get("asset_version")
		if _role(reference) in PASTE_ROLES and asset_version:
			path = _cutout_path(asset_version)
			if path:
				pasted.append({"role": _role(reference), "asset_version": asset_version, "path": path})
	return pasted


def layout(canvas, sizes_by_role):
	"""Place each subject: boxes (x, y, width, height) with the asset's aspect ratio unchanged.

	`sizes_by_role` is a list of (role, width, height) of the real assets. Characters and products stand on a
	common baseline, evenly spaced; logos sit in the top corners.
	"""
	canvas_width, canvas_height = canvas
	subjects = [i for i, (role, _w, _h) in enumerate(sizes_by_role) if role != "logo"]
	boxes = [None] * len(sizes_by_role)
	for rank, index in enumerate(subjects):
		role, width, height = sizes_by_role[index]
		slot = SPACING_MARGIN * canvas_width / (len(subjects) + 1)
		scale = min(SUBJECT_HEIGHT[role] * canvas_height / height, slot / width)
		box_width, box_height = round(width * scale), round(height * scale)
		center = (rank + 1) * canvas_width / (len(subjects) + 1)
		boxes[index] = (round(center - box_width / 2), round(BASELINE * canvas_height - box_height), box_width, box_height)
	logos = [i for i, (role, _w, _h) in enumerate(sizes_by_role) if role == "logo"]
	for rank, index in enumerate(logos):
		_role_name, width, height = sizes_by_role[index]
		scale = min(LOGO_MAX_WIDTH * canvas_width / width, LOGO_MAX_HEIGHT * canvas_height / height)
		box_width, box_height = round(width * scale), round(height * scale)
		margin = round(LOGO_MARGIN * canvas_width)
		x = margin if rank % 2 == 0 else canvas_width - margin - box_width
		boxes[index] = (x, margin, box_width, box_height)
	return boxes


def composite_subjects(background_bytes, subjects):
	"""PNG bytes of the background with the subjects pasted at their exact aspect ratio."""
	from PIL import Image, ImageFilter

	canvas = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
	assets = []
	for subject in subjects:
		with Image.open(subject["path"]) as source:
			asset = source.convert("RGBA")
		# Sizes and placement follow the visible subject, not the transparent margin around it.
		assets.append(asset.crop(asset.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()))
	boxes = layout(canvas.size, [(s["role"], a.width, a.height) for s, a in zip(subjects, assets)])
	for subject, asset, (x, y, width, height) in zip(subjects, assets, boxes):
		resized = asset.resize((width, height), Image.Resampling.LANCZOS)
		if subject["role"] != "logo":
			shadow = Image.new("L", canvas.size, 0)
			rim = max(2, round(height * 0.03))
			shadow.paste(110, (x + round(width * 0.1), y + height - rim, x + round(width * 0.9), y + height + rim))
			shadow = shadow.filter(ImageFilter.GaussianBlur(rim))
			canvas.paste(Image.new("RGBA", canvas.size, (0, 0, 0, 255)), (0, 0), shadow)
		canvas.alpha_composite(resized, (max(0, x), max(0, y)))
	output = io.BytesIO()
	canvas.convert("RGB").save(output, "PNG")
	return output.getvalue()


def paste_subjects_into_keyframe(attempt, image_bytes):
	"""A keyframe attempt's image with its shot's cutout references pasted in (unchanged when it has none).

	The references come from the run's frozen snapshot, so editing the shot later cannot change a render in flight.
	"""
	task = frappe.db.get_value("Generation Attempt", attempt.name, ["generation_task"], as_dict=True)
	shot, run = frappe.db.get_value("Generation Task", task.generation_task, ["shot", "generation_run"])
	try:
		snapshot = frappe.parse_json(frappe.db.get_value("Generation Run", run, "project_snapshot_json") or "{}")
	except (TypeError, ValueError):
		snapshot = {}
	shot_snapshot = next((row for row in (snapshot or {}).get("shots") or [] if row.get("shot") == shot), {})
	subjects = pasted_references(shot_snapshot.get("references"))
	return composite_subjects(image_bytes, subjects) if subjects else image_bytes
