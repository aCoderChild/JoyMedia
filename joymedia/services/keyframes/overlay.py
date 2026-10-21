"""Exact reproduction of the real mascot and product images in a keyframe, and of the product through its video.

An image model can only imitate a reference: proportions drift, claws blur, lettering turns to nonsense.
So a reference that is a transparent cutout (a Character, Product or Logo) is not given to the image model
at all. The model draws only the empty setting, and the real pixels are pasted over it afterwards with one
uniform scale factor, which keeps the asset's aspect ratio and every detail. A reference without
transparency cannot be pasted and still guides the image model as before.
"""

import io
import math
import re
from functools import lru_cache
from pathlib import Path

import frappe

from joymedia.services.project.tuning import tune

DRAW, PASTE = "Draw in scene", "Paste exact art"
DEFAULT_SETTING = "A bright, softly lit interior with a window and a clean floor, shallow depth of field."
SUBJECT_WORDS = re.compile(
	r"\b(hands?|fingers?|arms?|paws?|person|people|man|woman|child|kids?|babys?|animals?|mascots?|"
	r"characters?|products?|packs?|packets?|boxe?s?|bottles?|logos?|text|close-?ups?)\b",
	re.I,
)
EMPTY_SETTING = (
	"Establish the complete authored location in coherent perspective, retaining its specified architecture, "
	"furniture, ground and fixed props. Leave working surfaces clear unless the setting explicitly places "
	"an object on them. Keep described openings reachable and unobstructed by objects or overhanging furniture. "
	"Do not add decorative clutter to working areas or impose a different floor layout."
)


def usable_setting(text):
	"""The setting with every clause that names a subject left out: a pack, a person or a character in it would be
	drawn into the empty room (the real one is pasted or drawn from its own picture). The room and its furniture and
	objects stay ("a warm room with a table; a plate of cookies, a glass of water"). Nothing left: the default room."""
	clauses = [
		part.strip()
		for part in re.split(r"(?<=[.;])\s+|,\s+(?:and\s+)?", str(text or "").strip())
		if part.strip()
	]
	kept = [clause for clause in clauses if not SUBJECT_WORDS.search(clause)]
	if not kept:
		return DEFAULT_SETTING
	setting = ", ".join(clause.rstrip(".;,") for clause in kept)
	return setting[:1].upper() + setting[1:] + "."


def _role(reference):
	role = frappe.scrub(reference.get("reference_role") or reference.get("input_role") or "")
	# A real person (identity-locked from a photo) is a different input from a mascot or cartoon character.
	return "person" if role in ("person", "people", "talent") else role


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
			if image.convert("RGBA").getchannel("A").getextrema()[0] >= tune("opaque_below"):
				return None
	except OSError:
		return None
	return str(path)


PALETTE = {
	"white": (245, 245, 245),
	"cream": (240, 225, 200),
	"beige": (225, 200, 170),
	"light brown": (190, 140, 100),
	"brown": (120, 80, 50),
	"dark brown": (60, 40, 30),
	"grey": (140, 140, 140),
	"black": (20, 20, 20),
	"red": (200, 40, 40),
	"orange": (230, 130, 40),
	"yellow": (240, 210, 60),
	"green": (60, 160, 90),
	"teal": (60, 170, 160),
	"blue": (50, 100, 190),
	"pink": (240, 150, 180),
	"purple": (130, 80, 170),
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
			name = min(
				PALETTE,
				key=lambda n: sum((a - b) ** 2 for a, b in zip(PALETTE[n], (red, green, blue), strict=False)),
			)
			counts[name] = counts.get(name, 0) + 1
	total = sum(counts.values())
	if not total:
		return ""
	ranked = [
		name for name, count in sorted(counts.items(), key=lambda item: -item[1]) if count / total >= 0.08
	]
	main = [name for name in ranked if counts[name] / total >= 0.25] or ranked[:1]
	details = [name for name in ranked if name not in main][:2]
	return f"mostly {' and '.join(main)}" + (f", with {' and '.join(details)} details" if details else "")


def scene_mode(references, character_mode=PASTE):
	"""Respect the declared staging mode for actors, products and empty settings."""
	return DRAW if character_mode == DRAW else PASTE


def closes_film(shot, project=None):
	"""Whether this is the film's last scene: the advertisement's end card, where the product is the hero."""

	def field(row, key):
		return row.get(key) if hasattr(row, "get") else getattr(row, key, None)

	number = int(field(shot, "shot_number") or 0)
	shots = field(project, "shots") if project is not None else None
	if isinstance(shots, list) and shots:
		last = max(int(field(row, "shot_number") or 0) for row in shots)
	else:
		name = (
			(field(project, "media_project") or field(project, "name"))
			if project is not None
			else field(shot, "media_project")
		)
		last = (
			frappe.db.sql(
				"select max(shot_number) from `tabShot` where media_project = %s and is_removed = 0", name
			)[0][0]
			if name
			else None
		)
	return bool(number) and number == int(last or 0)


def pasted_references(references, character_mode=PASTE, context=None):
	"""The references that are pasted rather than shown to the image model, in the given order.

	The real product pack (its exact label and logo) is always pasted when it is a cutout; characters are pasted in
	"Paste exact art" mode and in a scene with no cast, and drawn from a reference board in a "Draw in scene" scene.
	A separate logo picture is never pasted on its own: the brand shows on the pack. `context` is the whole scene's
	references when `references` is only some of them.
	"""
	mode = scene_mode(context if context is not None else references, character_mode)
	roles = {"product"} if mode == DRAW else {"character", "product"}
	pasted = []
	for reference in references or []:
		asset_version = reference.get("asset_version")
		if _role(reference) == "product" and reference.get("preservation_mode") == "reference_guided":
			continue
		if _role(reference) in roles and asset_version:
			path = _cutout_path(asset_version)
			if path:
				pasted.append({"role": _role(reference), "asset_version": asset_version, "path": path})
	return pasted


def _any_image_path(asset_version):
	file_url = frappe.db.get_value("Asset Version", asset_version, "file")
	return str(frappe.get_doc("File", {"file_url": file_url}).get_full_path()) if file_url else None


def closing_subjects(references):
	"""Exact closing artwork, including ordinary JPEG reference photographs.

	Opaque photographs use disjoint presentation cells on white. Prepared alpha
	artwork uses the same cells without a photo background; RGB artwork is never redrawn.
	"""
	subjects = []
	for reference in references or []:
		role, version = _role(reference), reference.get("asset_version")
		if role == "product" and reference.get("preservation_mode") == "reference_guided":
			continue
		if role not in {"character", "product"} or not version:
			continue
		cutout = _cutout_path(version)
		path = cutout or _any_image_path(version)
		if path:
			subjects.append(
				{"role": role, "asset_version": version, "path": path, "opaque": not bool(cutout)}
			)
	return subjects


def character_board(references, scales=None, role="character"):
	"""A flat-background picture of a scene's characters side by side, as the image model's character reference.

	Each character keeps its own proportions and its relative size (the mother larger than the kid), standing on
	a common baseline, so the model sees who is who. Returns the PNG path, or None without a character picture.
	"""
	import hashlib

	from PIL import Image

	items = []
	for reference in references or []:
		path = _any_image_path(reference.get("asset_version")) if _role(reference) == role else None
		if path:
			with Image.open(path) as source:
				image = source.convert("RGBA")
			box = image.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
			items.append(
				(
					image.crop(box) if box else image,
					(scales or {}).get(reference.get("asset_version"), 1) or 1,
				)
			)
	if not items:
		return None
	largest = max(scale for _image, scale in items)
	height, gap = 768, 40
	tiles = []
	for image, scale in items:
		tile_height = round(height * 0.86 * scale / largest)
		tiles.append(
			image.resize(
				(max(1, round(image.width * tile_height / image.height)), tile_height),
				Image.Resampling.LANCZOS,
			)
		)
	width = sum(tile.width for tile in tiles) + gap * (len(tiles) + 1)
	board = Image.new("RGB", (width, height), (236, 232, 226))
	x = gap
	for tile in tiles:
		board.paste(tile, (x, height - tile.height - 30), tile)
		x += tile.width + gap
	folder = Path(frappe.get_site_path("private", "joymedia-boards"))
	folder.mkdir(parents=True, exist_ok=True)
	digest = hashlib.sha256(
		(
			f"{role}|"
			+ "|".join(
				f"{r.get('asset_version')}:{(scales or {}).get(r.get('asset_version'), 1)}"
				for r in references
			)
		).encode()
	).hexdigest()[:16]
	output = folder / f"{role}s-{digest}.png"
	board.save(output, "PNG")
	return str(output)


def boards_for_task(job):
	"""Reference boards for a keyframe task in "Draw in scene" mode: {"character": path}.

	Built from the run's frozen snapshot; a role with no picture has no board, and a scene in "Paste exact art"
	mode has none at all.
	"""
	snapshot = _run_snapshot(job.generation_run)
	shot = next((row for row in snapshot.get("shots") or [] if row.get("shot") == job.shot), {})
	if scene_mode(shot.get("references"), shot.get("character_mode") or PASTE) != DRAW:
		return {}
	scales = {row.get("asset_version"): row.get("scale") or 1 for row in snapshot.get("references") or []}
	path = character_board(shot.get("references"), scales, "character")
	return {"character": path} if path else {}


def scene_role_count(job, role):
	"""How many references of a role (e.g. "character") the task's scene has, from the run's frozen snapshot."""
	snapshot = _run_snapshot(job.generation_run)
	shot = next((row for row in snapshot.get("shots") or [] if row.get("shot") == job.shot), {})
	return sum(1 for reference in shot.get("references") or [] if _role(reference) == role)


def _run_snapshot(run_name):
	try:
		return (
			frappe.parse_json(
				frappe.db.get_value("Generation Run", run_name, "project_snapshot_json") or "{}"
			)
			or {}
		)
	except (TypeError, ValueError):
		return {}


def _fit(width, height, max_width, max_height):
	"""One uniform scale factor, so the aspect ratio is the asset's own."""
	scale = min(max_width / width, max_height / height)
	return round(width * scale), round(height * scale)


def hero_layout(canvas, sizes_by_role):
	"""Disjoint presentation cells keep opaque photographs off other subjects.

	Portrait cards stack cast above products; landscape cards place them beside
	each other. Source pixels retain their aspect ratio and a shared visual centre.
	No assumptions about a brand, species or particular number of references.
	"""
	w, h = canvas
	groups = [
		[i for i, item in enumerate(sizes_by_role) if item[0] == role] for role in ("character", "product")
	]
	groups = [group for group in groups if group]
	if sum(map(len, groups)) != len(sizes_by_role):
		raise ValueError("Hero composition supports character and product artwork only")
	boxes = [None] * len(sizes_by_role)
	portrait = h >= w
	for group_index, group in enumerate(groups):
		if len(groups) == 1:
			cell = (0.08 * w, 0.16 * h, 0.84 * w, 0.68 * h)
		elif portrait:
			# A marketing end card gives the product the primary presentation cell.
			cell = (
				(0.275 if group_index == 0 else 0.05) * w,
				(0.19 if group_index == 0 else 0.46) * h,
				(0.45 if group_index == 0 else 0.90) * w,
				(0.23 if group_index == 0 else 0.36) * h,
			)
		else:
			cell = (
				(0.04 if group_index == 0 else 0.36) * w,
				0.16 * h,
				(0.26 if group_index == 0 else 0.60) * w,
				0.68 * h,
			)
		x, y, width, height = cell
		gap = min(w, h) * 0.025
		available = width - gap * (len(group) - 1)
		shapes = []
		for index in group:
			_, source_width, source_height, *rest = sizes_by_role[index]
			scale = rest[0] if rest else 1
			if source_width <= 0 or source_height <= 0 or not isinstance(scale, (int, float)) or scale <= 0:
				raise ValueError("Source artwork dimensions and relative scale must be positive")
			shapes.append((source_width / source_height * scale, scale))
		if available <= 0:
			raise ValueError("Too many subjects for the hero canvas")
		unit = min(available / sum(a for a, _ in shapes), height / max(b for _, b in shapes))
		cursor = x + (width - unit * sum(a for a, _ in shapes) - gap * (len(group) - 1)) / 2
		baseline = y + (height + unit * max(b for _, b in shapes)) / 2
		for index, (rw, rh) in zip(group, shapes, strict=True):
			bw, bh = max(1, round(unit * rw)), max(1, round(unit * rh))
			boxes[index] = (round(cursor), round(baseline - bh), bw, bh)
			cursor += unit * rw + gap

	return boxes


def layout(canvas, sizes_by_role, product_center=None, product_hero=False, front=False):
	"""Place each subject: boxes (x, y, width, height) with the asset's aspect ratio unchanged.

	`sizes_by_role` is a list of (role, width, height[, scale]) of the real assets; scale is the subject's size
	relative to the others. Characters stand evenly spaced on a baseline; products stand in front as one family
	beside or between them, or, with no character pasted, large at `product_center` as the hero of the shot. With
	`product_hero` the subjects use disjoint cells arranged for the canvas aspect ratio.
	With `front` (characters drawn by the image model) the product stands on the floor in the lower middle, at an everyday
	size in front of the cast, where the prompt kept the floor clear. Every placement depends only on these inputs.
	"""
	if product_hero:
		return hero_layout(canvas, sizes_by_role)
	canvas_width, canvas_height = canvas
	boxes = [None] * len(sizes_by_role)
	groups = {
		role: [i for i, item in enumerate(sizes_by_role) if item[0] == role]
		for role in ("character", "product")
	}
	for _rank, index in enumerate(groups["character"]):
		_role_name, width, height, *rest = sizes_by_role[index]
		count = len(groups["character"])
		scales = [(sizes_by_role[i][3] if len(sizes_by_role[i]) > 3 else 1) for i in groups["character"]]
		# Sizes are relative to the largest character present, so a lone baby fills the frame like a lone mother.
		scale = (rest[0] if rest else 1) / max(scales)
		# The width budget is shared in proportion to each character's relative size.
		share = scale / sum(value / max(scales) for value in scales)
		box_width, box_height = _fit(
			width,
			height,
			tune("character_width") * canvas_width * share,
			tune("character_height") * canvas_height * scale,
		)
		center = (_rank + 1) * canvas_width / (count + 1)
		baseline = tune("character_baseline")
		boxes[index] = (
			round(center - box_width / 2),
			round(baseline * canvas_height) - box_height,
			box_width,
			box_height,
		)
	hero = boxes[groups["character"][0]] if groups["character"] else None
	if front:
		product_center = 0.5
	count = len(groups["product"])
	count = len(groups["product"])
	family_x = 0.0
	for index in groups["product"]:
		_role_name, width, height, *rest = sizes_by_role[index]
		scale = rest[0] if rest else 1
		size_key = "front_product" if front else "product" if hero else "hero_product"
		box_width, box_height = _fit(
			width,
			height,
			tune(f"{size_key}_width") * canvas_width / max(1, count * 0.75) * scale,
			tune(f"{size_key}_height") * canvas_height * scale,
		)
		if hero and count == 1:
			center = hero[0] + hero[2] / 2 + tune("product_offset") * canvas_width
		elif count == 1:
			center = (product_center or 0.5) * canvas_width
		else:
			# Several products stand together, each overlapping its neighbour a little.
			center = (product_center or 0.5) * canvas_width + family_x
			family_x += box_width * 0.75
		boxes[index] = [center, box_width, box_height]
	if count > 1:
		# Centre the family: shift every product left by half the spread.
		spread = (family_x - boxes[groups["product"][-1]][1] * 0.75) / 2
		for index in groups["product"]:
			boxes[index][0] -= spread
	for index in groups["product"]:
		center, box_width, box_height = boxes[index]
		bottom = (
			(hero[1] + hero[3] + tune("product_near") * canvas_height)
			if hero
			else tune("front_product_baseline") * canvas_height
			if front
			else tune("product_baseline") * canvas_height
		)
		margin = tune("edge_margin") * canvas_width
		x = min(max(center - box_width / 2, margin), canvas_width - margin - box_width)
		boxes[index] = (
			round(x),
			round(min(bottom, 0.97 * canvas_height)) - box_height,
			box_width,
			box_height,
		)
	return boxes


def _contact_shadow(canvas, x, y, width, height):
	"""A tight dark shadow where the subject touches the floor, under a wider soft one."""
	from PIL import Image, ImageDraw, ImageFilter

	shadow = Image.new("L", canvas.size, 0)
	rim = max(3, round(height * 0.035))
	base = y + height - round(rim * 1.3)
	ImageDraw.Draw(shadow).ellipse((x + width * 0.05, base - rim, x + width * 0.95, base + rim * 2), fill=55)
	shadow = shadow.filter(ImageFilter.GaussianBlur(rim * 1.6))
	tight = Image.new("L", canvas.size, 0)
	ImageDraw.Draw(tight).ellipse(
		(x + width * 0.15, base - rim * 0.3, x + width * 0.85, base + rim * 0.5), fill=75
	)
	tight = tight.filter(ImageFilter.GaussianBlur(rim * 0.5))
	for layer in (shadow, tight):
		canvas.paste(Image.new("RGBA", canvas.size, (0, 0, 0, 255)), (0, 0), layer)


def _emptier_side(canvas):
	"""Where a product can stand when the characters are already drawn: the side of the floor with less detail.

	Returns the horizontal centre as a fraction of the width (0.27 or 0.73).
	"""
	from PIL import ImageFilter, ImageStat

	width, height = canvas.size
	floor = canvas.convert("L").crop((0, round(0.6 * height), width, height)).filter(ImageFilter.FIND_EDGES)
	left = ImageStat.Stat(floor.crop((0, 0, width // 2, floor.height))).mean[0]
	right = ImageStat.Stat(floor.crop((width // 2, 0, width, floor.height))).mean[0]
	return 0.27 if left <= right else 0.73


def shared_ground_layout(canvas, sizes):
	"""Place prepared artwork beside each other on one authored studio baseline."""
	w, h = canvas
	if not sizes or len(sizes) > 12:
		raise ValueError("A shared studio ground needs 1-12 subjects")
	shapes = []
	for _role, width, height, *scale in sizes:
		relative = scale[0] if scale else 1
		if (
			any(
				type(value) not in (int, float) or not math.isfinite(value) or value <= 0
				for value in (width, height, relative)
			)
			or relative > 100
		):
			raise ValueError("Artwork dimensions and relative scale must be positive")
		shapes.append((width / height * relative, relative))
	gap = min(w, h) * 0.035
	unit = min(
		(w * 0.84 - gap * (len(shapes) - 1)) / sum(x for x, _ in shapes), h * 0.52 / max(y for _, y in shapes)
	)
	if unit <= 0:
		raise ValueError("Too many subjects for the studio ground")
	cursor = (w - unit * sum(x for x, _ in shapes) - gap * (len(shapes) - 1)) / 2
	baseline = round(h * 0.72)
	boxes = []
	for width, height in shapes:
		bw, bh = max(1, round(unit * width)), max(1, round(unit * height))
		boxes.append((round(cursor), baseline - bh, bw, bh))
		cursor += bw + gap
	return boxes


def composite_subjects(
	background_bytes,
	subjects,
	shadows=True,
	hero=False,
	front=False,
	lock=None,
	shared_ground=False,
	placements=None,
):
	"""PNG bytes of the background with the subjects pasted at their exact aspect ratio.

	`hero` makes the product the large centre of a closing scene; `front` stands it in front of drawn characters. When
	`lock` is a dict it receives the canvas size and, per pasted product, its box and the exact pasted pixels (PNG), so
	the scene's video can show the very same pack (see lock_products_in_video).
	"""
	from PIL import Image, ImageFilter

	canvas = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
	if hero:
		canvas = Image.new("RGBA", canvas.size, "white")
	assets = []
	for subject in subjects:
		with Image.open(subject["path"]) as source:
			asset = source.convert("RGBA")
		if shared_ground and asset.getchannel("A").getextrema()[0] >= 250:
			raise ValueError(
				"Shared studio ground requires transparent prepared artwork, not photograph panels"
			)
		# Sizes and placement follow the visible subject, not the transparent margin around it.
		assets.append(asset.crop(asset.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()))
	has_character = any(s["role"] == "character" for s in subjects)
	sizes = [
		(s["role"], a.width, a.height, s.get("scale", 1)) for s, a in zip(subjects, assets, strict=False)
	]
	boxes = (
		shared_ground_layout(canvas.size, sizes)
		if shared_ground
		else layout(
			canvas.size,
			sizes,
			product_center=None if has_character or front else (0.5 if hero else _emptier_side(canvas)),
			product_hero=hero,
			front=front,
		)
	)
	if placements:
		from joymedia.services.scene.artwork import fit_box

		requested = {row["asset_version"]: row["box"] for row in placements}
		available = {subject.get("asset_version") for subject in subjects}
		if set(requested) - available:
			raise ValueError("Artwork placement must name a selected transparent source asset.")
		for index, (subject, asset) in enumerate(zip(subjects, assets, strict=False)):
			if subject.get("asset_version") in requested:
				if asset.getchannel("A").getextrema()[0] >= 250:
					raise ValueError("Placed artwork requires a transparent cutout, not a photo panel.")
				boxes[index] = fit_box(canvas.size, asset.size, requested[subject["asset_version"]])
	if lock is not None:
		lock.update({"canvas": list(canvas.size), "items": []})
	# Painting order: characters, then products; on the end card the centre product (the first) is painted last, in front.
	products = [i for i, s in enumerate(subjects) if s["role"] == "product"]
	order = [i for i, s in enumerate(subjects) if s["role"] != "product"] + (
		products[1:] + products[:1] if hero else products
	)
	for subject, asset, (x, y, width, height) in ((subjects[i], assets[i], boxes[i]) for i in order):
		resized = asset.resize((width, height), Image.Resampling.LANCZOS)
		# A softer edge and a touch of the room's colour make the cutout sit in the scene instead of on it.
		alpha = resized.getchannel("A").filter(ImageFilter.GaussianBlur(0.7))
		room = canvas.crop(
			(max(0, x), max(0, y), min(canvas.width, x + width), min(canvas.height, y + height))
		)
		tint = Image.new(
			"RGB", resized.size, room.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
		)
		rgb = resized.convert("RGB")
		if subject["role"] != "product" and not hero:
			rgb = Image.blend(rgb, tint, tune("colour_match"))
		# Light falls off toward the floor: darken the lowest quarter a little, as in contact with the ground.
		ramp = (
			Image.linear_gradient("L")
			.resize(rgb.size)
			.point(lambda v: round((v - 190) * 0.6) if v > 190 else 0)
		)
		if subject["role"] != "product" and not hero:
			rgb = Image.composite(Image.new("RGB", rgb.size, (0, 0, 0)), rgb, ramp)
		resized = Image.merge("RGBA", (*rgb.split(), alpha))
		if shadows:
			_contact_shadow(canvas, x, y, width, height)
		canvas.alpha_composite(resized, (max(0, x), max(0, y)))
		if lock is not None and subject["role"] == "product":
			patch = io.BytesIO()
			resized.save(patch, "PNG")
			lock["items"].append(
				{
					"box": [max(0, x), max(0, y), width, height],
					"png": patch.getvalue(),
					"source_asset_version": subject.get("asset_version"),
				}
			)
	output = io.BytesIO()
	canvas.convert("RGB").save(output, "PNG")
	return output.getvalue()


def paste_subjects_into_keyframe(attempt, image_bytes, lock=None):
	"""A keyframe attempt's image with its shot's cutout references pasted in (unchanged when it has none).

	The references come from the run's frozen snapshot, so editing the shot later cannot change a render in flight.
	"""
	task = frappe.db.get_value("Generation Attempt", attempt.name, ["generation_task"], as_dict=True)
	shot, run = frappe.db.get_value("Generation Task", task.generation_task, ["shot", "generation_run"])
	try:
		snapshot = frappe.parse_json(
			frappe.db.get_value("Generation Run", run, "project_snapshot_json") or "{}"
		)
	except (TypeError, ValueError):
		snapshot = {}
	shot_snapshot = next((row for row in (snapshot or {}).get("shots") or [] if row.get("shot") == shot), {})
	from joymedia.services.consistency.retention import RetentionRejected, required_sources, retain
	from joymedia.services.scene.artwork import placements

	# Draw-in-scene packshots use the same measured placement/matting as every
	# other shot. The final scene number does not authorize a white photo collage.
	staged = scene_mode(shot_snapshot.get("references"), shot_snapshot.get("character_mode") or PASTE) == DRAW
	if (
		(staged or not closes_film(shot_snapshot, snapshot))
		and shot_snapshot.get("reference_retention")
		and required_sources(shot_snapshot.get("references"))
		and not placements(shot_snapshot.get("motion_plan_json"))
	):
		# Keep the provider's staging as a proposal, but never its package artwork.
		try:
			return retain(
				attempt,
				image_bytes,
				shot_snapshot.get("references"),
				shot_snapshot["reference_retention"],
				lock if lock is not None else {},
			)
		except ValueError as exc:
			raise RetentionRejected(str(exc)) from exc
	hero = closes_film(shot_snapshot, snapshot) and not staged
	mode = scene_mode(shot_snapshot.get("references"), shot_snapshot.get("character_mode") or PASTE)
	subjects = (
		closing_subjects(shot_snapshot.get("references"))
		if hero
		else pasted_references(shot_snapshot.get("references"), shot_snapshot.get("character_mode") or PASTE)
	)
	scales = {
		row.get("asset_version"): row.get("scale") or 1 for row in (snapshot or {}).get("references") or []
	}
	for subject in subjects:
		subject["scale"] = scales.get(subject["asset_version"], 1)
	from joymedia.services.keyframes.locations import shot_views

	views = shot_views(shot_snapshot)
	if views:
		return split_screen_keyframe(
			image_bytes,
			views,
			shot_snapshot.get("setting_prompt"),
			snapshot.get("media_project"),
			subjects,
			lock,
		)
	from joymedia.services.planning.prompts import holds_product

	if holds_product(frappe._dict(shot_snapshot)):
		held = paste_held_product(image_bytes, subjects, lock)
		if held:
			return held
	from joymedia.services.scene.artwork import placements

	authored = placements(shot_snapshot.get("motion_plan_json"))
	if authored:
		from PIL import Image

		from joymedia.services.scene.artwork import fit_box, validate_surface_contact

		with Image.open(io.BytesIO(image_bytes)) as canvas:
			canvas_size = canvas.size
		by_source = {row["asset_version"]: row for row in authored}
		try:
			for subject in subjects:
				if subject["role"] != "product":
					continue
				row = by_source.get(subject["asset_version"], {})
				with Image.open(subject["path"]) as source:
					asset = source.convert("RGBA")
				asset = asset.crop(asset.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox())
				if not row:
					raise ValueError("A product has no explicit source placement.")
				proof = validate_surface_contact(
					image_bytes,
					canvas_size,
					asset,
					fit_box(canvas_size, asset.size, row["box"]),
					row.get("support_surface"),
				)
				if lock is not None:
					lock.setdefault("provenance", []).append(
						{**proof, "source_asset_version": subject["asset_version"]}
					)
		except ValueError as exc:
			raise RetentionRejected(str(exc)) from exc
		return composite_subjects(image_bytes, subjects, lock=lock, placements=authored)
	if not hero and any(subject["role"] == "product" for subject in subjects):
		raise RetentionRejected(
			"No measured product surface is available. Heuristic product placement in a scene is disabled."
		)
	# The closing scene makes the product the hero; elsewhere a drawn scene stands it in front of the cast.
	front = mode == DRAW and not hero
	return (
		composite_subjects(image_bytes, subjects, hero=hero, front=front, lock=lock)
		if subjects
		else image_bytes
	)


def paste_held_product(image_bytes, subjects, lock=None):
	"""The frame with the real pack pasted over the pack the character was drawn holding, or None when it is not found.

	The sheet has a character hold the product, so the image model draws it in the character's arms; its drawing of the
	print is never exact, so the vision model finds it (review.consistency.locate) and the cutout covers it exactly."""
	from PIL import Image

	from joymedia.services.review.consistency import locate

	products = [subject for subject in subjects if subject["role"] == "product"]
	if not products:
		return None
	box = locate(image_bytes, "the product pack the character holds in its arms")
	if not box:
		return None
	canvas = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
	with Image.open(products[0]["path"]) as source:
		cutout = source.convert("RGBA")
	cutout = cutout.crop(cutout.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox())
	left, top, right, bottom = box
	# Cover the drawn pack entirely (no part of its print left showing), keeping the real pack's shape.
	scale = max((right - left) / cutout.width, (bottom - top) / cutout.height)
	width, height = max(1, round(cutout.width * scale)), max(1, round(cutout.height * scale))
	x, y = round((left + right - width) / 2), round((top + bottom - height) / 2)
	resized = cutout.resize((width, height), Image.Resampling.LANCZOS)
	canvas.alpha_composite(resized, (max(0, x), max(0, y)))
	if lock is not None:
		patch = io.BytesIO()
		resized.save(patch, "PNG")
		lock.update(
			{
				"canvas": list(canvas.size),
				"items": [{"box": [max(0, x), max(0, y), width, height], "png": patch.getvalue()}],
			}
		)
	output = io.BytesIO()
	canvas.convert("RGB").save(output, "PNG")
	return output.getvalue()


def split_screen_keyframe(image_bytes, views, setting, project_name, subjects, lock=None):
	"""The first frame of a split screen: one panel per view, top to bottom, separated by thin white lines.

	Each panel is its view's own place picture (keyframes.locations: the film's room for a view of that room, so it
	matches the other scenes), with the scene's pasted subjects, the real product pack, large in its middle. A view
	with no picture shows the drawn frame. `lock` receives every pasted pack, in frame coordinates.
	"""
	from PIL import Image, ImageOps

	from joymedia.services.keyframes.locations import view_key

	with Image.open(io.BytesIO(image_bytes)) as drawn:
		width, height = drawn.size
	gap = max(4, round(height * 0.006))
	band = (height - gap * (len(views) - 1)) // len(views)
	project = (
		frappe.get_doc("Media Project", project_name) if project_name else frappe._dict(selected_media=[])
	)
	pictures = {
		row.reference_key: row.asset_version for row in project.selected_media or [] if row.reference_key
	}
	frame = Image.new("RGB", (width, height), "white")
	if lock is not None:
		lock.update({"canvas": [width, height], "items": []})
	for index, view in enumerate(views):
		version = pictures.get(view_key(project, view["text"], setting))
		file_url = frappe.db.get_value("Asset Version", version, "file") if version else None
		source = frappe.get_doc("File", {"file_url": file_url}).get_content() if file_url else image_bytes
		with Image.open(io.BytesIO(source)) as picture:
			panel = ImageOps.fit(picture.convert("RGB"), (width, band), method=Image.Resampling.LANCZOS)
		buffer = io.BytesIO()
		panel.save(buffer, "PNG")
		panel_lock = {} if lock is not None else None
		filled = (
			composite_subjects(buffer.getvalue(), subjects, hero=True, lock=panel_lock)
			if subjects
			else buffer.getvalue()
		)
		top = index * (band + gap)
		with Image.open(io.BytesIO(filled)) as panel:
			frame.paste(panel.convert("RGB"), (0, top))
		for item in (panel_lock or {}).get("items", []):
			x, y, item_width, item_height = item["box"]
			lock["items"].append({"box": [x, y + top, item_width, item_height], "png": item["png"]})
	output = io.BytesIO()
	frame.save(output, "PNG")
	return output.getvalue()


def store_product_lock(artifact, lock):
	"""Save each pasted pack's exact pixels as a private file and return the lock as JSON for the artifact."""
	import json

	items = []
	for number, item in enumerate(lock["items"], 1):
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{artifact.name}-product-{number}.png",
				"content": item["png"],
				"is_private": 1,
				"attached_to_doctype": "Generation Artifact",
				"attached_to_name": artifact.name,
			}
		).insert(ignore_permissions=True)
		items.append(
			{
				"box": item["box"],
				"file": file_doc.file_url,
				**(
					{"source_asset_version": item["source_asset_version"]}
					if item.get("source_asset_version")
					else {}
				),
			}
		)
	return json.dumps(
		{
			"canvas": lock["canvas"],
			"items": items,
			**({"provenance": lock["provenance"]} if lock.get("provenance") else {}),
		}
	)


class SourceArtCoverageError(ValueError):
	"""A fixed overlay cannot protect every frame."""


THUMB = 32


def _region_thumbnails(video_path, box):
	"""Each frame's pack region as a THUMB x THUMB grey thumbnail (bytes), read with ffmpeg."""
	import subprocess

	x, y, width, height = box
	raw = subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-i",
			str(video_path),
			"-vf",
			f"crop={width}:{height}:{x}:{y},scale={THUMB}:{THUMB},format=gray",
			"-f",
			"rawvideo",
			"-",
		],
		capture_output=True,
		check=True,
	).stdout
	size = THUMB * THUMB
	return [raw[i : i + size] for i in range(0, len(raw) - size + 1, size)]


def pack_still_frames(thumbs, mask=None, tolerance=None):
	"""Which frames still show the pack where the first frame has it: [(first, last), …] frame ranges.

	The camera can move or cut despite the prompt; pasting the pack then would put it onto something else. A frame
	counts when its pack region differs from the first frame's by less than `tolerance` (mean grey level, 0-255, over
	the pack's own pixels); one-to-three-frame dropouts are bridged and runs shorter than a quarter second are dropped.
	"""
	from joymedia.services.project.tuning import tune

	tolerance = tune("pack_lock_tolerance") if tolerance is None else tolerance
	if not thumbs:
		return []
	first = thumbs[0]
	pixels = [i for i in range(len(first)) if mask is None or mask[i]] or list(range(len(first)))
	still = [sum(abs(frame[i] - first[i]) for i in pixels) / len(pixels) < tolerance for frame in thumbs]
	for index in range(1, len(still) - 1):  # bridge short dropouts (a paw passing, a flicker)
		if not still[index] and any(still[max(0, index - 3) : index]) and any(still[index + 1 : index + 4]):
			still[index] = True
	ranges, start = [], None
	for index, ok in enumerate([*still, False]):
		if ok and start is None:
			start = index
		elif not ok and start is not None:
			if index - start >= 6:
				ranges.append((start, index - 1))
			start = None
	return ranges


def lock_products_in_video(video_path, lock, output_path, fps):
	"""Lay the keyframe's exact product pixels over the frames of the scene's video where the pack is still in place.

	The video model redraws the pack in every frame, so its label and logo drift and warp. The prompt keeps the pack
	still and the camera locked, so the pack normally stays where the keyframe put it, and the real pixels go back on
	top. Frames where the camera moved or cut anyway are left as rendered (see pack_still_frames). Returns None when
	no frame needs the pack, so the caller keeps the video unchanged.
	"""
	import json
	import subprocess

	lock = json.loads(lock) if isinstance(lock, str) else lock
	probe = subprocess.run(
		[
			"ffprobe",
			"-v",
			"error",
			"-select_streams",
			"v:0",
			"-show_entries",
			"stream=width,height",
			"-of",
			"csv=p=0",
			str(video_path),
		],
		capture_output=True,
		text=True,
		check=True,
	)
	video_width, video_height = (int(value) for value in probe.stdout.strip().split(",")[:2])
	scale_x, scale_y = video_width / lock["canvas"][0], video_height / lock["canvas"][1]
	inputs, graph, label = [], [], "0:v"
	from PIL import Image

	for item in lock["items"]:
		path = frappe.get_doc("File", {"file_url": item["file"]}).get_full_path()
		x, y, width, height = item["box"]
		box = (
			round(x * scale_x),
			round(y * scale_y),
			max(2, round(width * scale_x)),
			max(2, round(height * scale_y)),
		)
		box = (box[0], box[1], min(box[2], video_width - box[0]), min(box[3], video_height - box[1]))
		with Image.open(path) as patch:
			mask = [value > 128 for value in patch.getchannel("A").resize((THUMB, THUMB)).tobytes()]
		thumbs = _region_thumbnails(video_path, box)
		space = item.get("coordinate_space", "world")
		if space not in {"world", "screen"}:
			raise ValueError("Unknown protected artwork coordinate space.")
		if space == "screen" and item.get("kind") != "typography":
			raise ValueError("Screen-space protection requires declared typography.")
		ranges = [(0, len(thumbs) - 1)] if space == "screen" and thumbs else pack_still_frames(thumbs, mask)
		# A partial overlay is not an exact-art lock. Refuse the take instead of
		# silently leaving distorted label frames in a supposedly protected clip.
		covered = {frame for start, end in ranges for frame in range(start, end + 1)}
		if len(covered) != len(thumbs) or not thumbs:
			raise SourceArtCoverageError(
				"Product source-art lock lost coverage. Use tracked source-art repair with explicit occlusion controls; this take was not protected."
			)
		index = len(inputs) // 6  # one "-loop 1 -framerate fps -i path" group per pack placed so far
		# The still must run at the video's rate: at ffmpeg's default 25 fps the overlay drifts and drops near the end.
		inputs += ["-loop", "1", "-framerate", f"{fps:g}", "-i", path]
		enable = "+".join(f"between(n,{first},{last})" for first, last in ranges)
		graph.append(f"[{index + 1}:v]scale={box[2]}:{box[3]}:flags=lanczos,format=rgba[pack{index}]")
		graph.append(
			f"[{label}][pack{index}]overlay=x={box[0]}:y={box[1]}:shortest=1:enable='{enable}'[locked{index}]"
		)
		label = f"locked{index}"
	if not graph:
		return None
	subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-y",
			"-i",
			str(video_path),
			*inputs,
			"-filter_complex",
			";".join(graph),
			"-map",
			f"[{label}]",
			"-map",
			"0:a?",
			"-c:a",
			"copy",
			"-c:v",
			"libx264",
			"-pix_fmt",
			"yuv420p",
			"-crf",
			"16",
			"-r",
			f"{fps:g}",
			str(output_path),
		],
		check=True,
		capture_output=True,
	)
	return output_path
