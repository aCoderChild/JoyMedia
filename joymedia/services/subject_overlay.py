"""Exact reproduction of the real mascot, product and logo images in a keyframe.

An image model can only imitate a reference: proportions drift, claws blur, lettering turns to nonsense.
So a reference that is a transparent cutout (a Character, Product or Logo) is not given to the image model
at all. The model draws only the empty setting, and the real pixels are pasted over it afterwards with one
uniform scale factor, which keeps the asset's aspect ratio and every detail. A reference without
transparency cannot be pasted and still guides the image model as before.
"""

import io
import re
from functools import lru_cache
from pathlib import Path

import frappe

PASTE_ROLES = frozenset({"character", "product", "logo"})
# Fractions of the canvas: a character is the hero of the frame, a product sits in front of it.
CHARACTER_HEIGHT, CHARACTER_WIDTH, CHARACTER_BASELINE = 0.36, 0.70, 0.86
PRODUCT_HEIGHT, PRODUCT_WIDTH, PRODUCT_BASELINE = 0.15, 0.40, 0.90
# With a character, a product stands beside it on the same floor, slightly nearer the camera.
PRODUCT_NEAR, PRODUCT_OFFSET, EDGE_MARGIN = 0.03, 0.22, 0.02
COLOUR_MATCH = 0.16
LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT, LOGO_MARGIN = 0.22, 0.08, 0.04
OPAQUE_BELOW = 250

DEFAULT_SETTING = "A bright, softly lit interior with a window and a clean floor, shallow depth of field."
SUBJECT_WORDS = re.compile(
	r"\b(hands?|fingers?|arms?|paws?|person|people|man|woman|child|kids?|babys?|bears?|cubs?|animals?|mascots?|"
	r"characters?|products?|packs?|packets?|boxe?s?|bottles?|tissues?|paper|napkins?|logos?|text|close-?ups?)\b",
	re.I,
)
EMPTY_SETTING = (
	"A wide view of an empty, uninhabited room seen from standing height, with a large, open, clear floor filling "
	"the lower third of the frame and nothing standing on it."
)


def usable_setting(text):
	"""The planner's setting if it describes only a place; any subject in it would be drawn into the empty setting."""
	text = str(text or "").strip()
	return text if text and not SUBJECT_WORDS.search(text) else DEFAULT_SETTING


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


PALETTE = {
	"white": (245, 245, 245), "cream": (240, 225, 200), "beige": (225, 200, 170), "light brown": (190, 140, 100),
	"brown": (120, 80, 50), "dark brown": (60, 40, 30), "grey": (140, 140, 140), "black": (20, 20, 20),
	"red": (200, 40, 40), "orange": (230, 130, 40), "yellow": (240, 210, 60), "green": (60, 160, 90),
	"teal": (60, 170, 160), "blue": (50, 100, 190), "pink": (240, 150, 180), "purple": (130, 80, 170),
}


@lru_cache(maxsize=256)
def describe_colours(asset_version):
	"""The main colours of an Asset Version's visible pixels, in words ("mostly cream, with brown details")."""
	from PIL import Image

	file_url = frappe.db.get_value("Asset Version", asset_version, "file")
	if not file_url:
		return ""
	try:
		with Image.open(frappe.get_doc("File", {"file_url": file_url}).get_full_path()) as image:
			image = image.convert("RGBA")
	except OSError:
		return ""
	image.thumbnail((64, 64))
	counts = {}
	for red, green, blue, alpha in image.getdata():
		if alpha > 128:
			name = min(PALETTE, key=lambda n: sum((a - b) ** 2 for a, b in zip(PALETTE[n], (red, green, blue))))
			counts[name] = counts.get(name, 0) + 1
	total = sum(counts.values())
	if not total:
		return ""
	ranked = [name for name, count in sorted(counts.items(), key=lambda item: -item[1]) if count / total >= 0.08]
	main = [name for name in ranked if counts[name] / total >= 0.25] or ranked[:1]
	details = [name for name in ranked if name not in main][:2]
	return f"mostly {' and '.join(main)}" + (f", with {' and '.join(details)} details" if details else "")


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


def _fit(width, height, max_width, max_height):
	"""One uniform scale factor, so the aspect ratio is the asset's own."""
	scale = min(max_width / width, max_height / height)
	return round(width * scale), round(height * scale)


def layout(canvas, sizes_by_role):
	"""Place each subject: boxes (x, y, width, height) with the asset's aspect ratio unchanged.

	`sizes_by_role` is a list of (role, width, height[, scale]) of the real assets; scale is the subject's size
	relative to the others. Characters stand evenly spaced on a baseline, products stand in front as one family
	beside or between them, logos sit in the top corners.
	"""
	canvas_width, canvas_height = canvas
	boxes = [None] * len(sizes_by_role)
	groups = {role: [i for i, item in enumerate(sizes_by_role) if item[0] == role] for role in ("character", "product", "logo")}
	for rank, index in enumerate(groups["character"]):
		_role_name, width, height, *rest = sizes_by_role[index]
		count = len(groups["character"])
		scale = rest[0] if rest else 1
		# The width budget is shared in proportion to each character's relative size.
		share = scale / sum((sizes_by_role[i][3] if len(sizes_by_role[i]) > 3 else 1) for i in groups["character"])
		box_width, box_height = _fit(
			width, height, CHARACTER_WIDTH * canvas_width * share, CHARACTER_HEIGHT * canvas_height * scale
		)
		center = (rank + 1) * canvas_width / (count + 1)
		boxes[index] = (round(center - box_width / 2), round(CHARACTER_BASELINE * canvas_height) - box_height, box_width, box_height)
	hero = boxes[groups["character"][0]] if groups["character"] else None
	count = len(groups["product"])
	family_x = 0.0
	for rank, index in enumerate(groups["product"]):
		_role_name, width, height, *rest = sizes_by_role[index]
		scale = rest[0] if rest else 1
		box_width, box_height = _fit(
			width, height, PRODUCT_WIDTH * canvas_width / max(1, count * 0.75) * scale, PRODUCT_HEIGHT * canvas_height * scale
		)
		if hero and count == 1:
			center = hero[0] + hero[2] / 2 + PRODUCT_OFFSET * canvas_width
		elif count == 1:
			center = 0.5 * canvas_width
		else:
			# Several products stand together in the middle of the frame, each overlapping its neighbour a little.
			center = canvas_width / 2 + family_x
			family_x += box_width * 0.75
		boxes[index] = [center, box_width, box_height]
	if count > 1:
		# Centre the family: shift every product left by half the spread.
		spread = (family_x - boxes[groups["product"][-1]][1] * 0.75) / 2
		for index in groups["product"]:
			boxes[index][0] -= spread
	for index in groups["product"]:
		center, box_width, box_height = boxes[index]
		bottom = (hero[1] + hero[3] + PRODUCT_NEAR * canvas_height) if hero else PRODUCT_BASELINE * canvas_height
		margin = EDGE_MARGIN * canvas_width
		x = min(max(center - box_width / 2, margin), canvas_width - margin - box_width)
		boxes[index] = (round(x), round(min(bottom, 0.97 * canvas_height)) - box_height, box_width, box_height)
	for rank, index in enumerate(groups["logo"]):
		_role_name, width, height, *_scale = sizes_by_role[index]
		box_width, box_height = _fit(width, height, LOGO_MAX_WIDTH * canvas_width, LOGO_MAX_HEIGHT * canvas_height)
		margin = round(LOGO_MARGIN * canvas_width)
		boxes[index] = (margin if rank % 2 == 0 else canvas_width - margin - box_width, margin, box_width, box_height)
	return boxes


def _contact_shadow(canvas, x, y, width, height):
	"""A tight dark shadow where the subject touches the floor, under a wider soft one."""
	from PIL import Image, ImageFilter

	shadow = Image.new("L", canvas.size, 0)
	rim = max(3, round(height * 0.035))
	base = y + height - round(rim * 1.3)
	shadow.paste(95, (x + round(width * 0.0), base - rim, x + round(width * 1.0), base + rim * 2))
	shadow = shadow.filter(ImageFilter.GaussianBlur(rim * 1.6))
	tight = Image.new("L", canvas.size, 0)
	tight.paste(185, (x + round(width * 0.10), base - round(rim * 0.5), x + round(width * 0.90), base + round(rim * 0.8)))
	tight = tight.filter(ImageFilter.GaussianBlur(rim * 0.5))
	for layer in (shadow, tight):
		canvas.paste(Image.new("RGBA", canvas.size, (0, 0, 0, 255)), (0, 0), layer)


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
	boxes = layout(canvas.size, [(s["role"], a.width, a.height, s.get("scale", 1)) for s, a in zip(subjects, assets)])
	for subject, asset, (x, y, width, height) in zip(subjects, assets, boxes):
		resized = asset.resize((width, height), Image.Resampling.LANCZOS)
		# A softer edge and a touch of the room's colour make the cutout sit in the scene instead of on it.
		alpha = resized.getchannel("A").filter(ImageFilter.GaussianBlur(0.7))
		if subject["role"] != "logo":
			room = canvas.crop((max(0, x), max(0, y), min(canvas.width, x + width), min(canvas.height, y + height)))
			tint = Image.new("RGB", resized.size, room.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0)))
			rgb = Image.blend(resized.convert("RGB"), tint, COLOUR_MATCH)
			# Light falls off toward the floor: darken the lowest quarter a little, as in contact with the ground.
			ramp = Image.linear_gradient("L").resize(rgb.size).point(lambda v: round((v - 190) * 0.6) if v > 190 else 0)
			rgb = Image.composite(Image.new("RGB", rgb.size, (0, 0, 0)), rgb, ramp)
			resized = Image.merge("RGBA", (*rgb.split(), alpha))
			_contact_shadow(canvas, x, y, width, height)
		else:
			resized.putalpha(alpha)
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
	scales = {row.get("asset_version"): row.get("scale") or 1 for row in (snapshot or {}).get("references") or []}
	for subject in subjects:
		subject["scale"] = scales.get(subject["asset_version"], 1)
	return composite_subjects(image_bytes, subjects) if subjects else image_bytes
