"""Character close-ups are drawn wide at double size and cropped in code.

Given a full-body pose reference, the picture model copied that framing whatever
the close-up text said (27 full-body "close-ups" rejected by 2026-10-30). It
draws a medium shot reliably, so a close character frame is drawn at twice the
delivery size and the focal region the scene names is cropped back to the
delivery size. The crop never upscales, cannot contain the feet, and every
check then judges the cropped frame.
"""

import io
import math
import re

import frappe

DETAIL_SCALE = 2
CLOSE_FRAMINGS = {"close_up", "extreme_close_up"}
CAST_ROLES = {"character", "person", "people", "talent"}
FOCUS_EDGE = 1024
FOCUS_MARGIN = 1.3
# The observer grounds a short object name far better than a scene sentence (asked for
# "the mascot's face" in a sentence, it boxed the whole character).
FOCUS = (
	"Locate {target} in this image. Return JSON bbox_2d=[left,top,right,bottom] in PIXEL coordinates "
	"of the image you received, tightly enclosing only {target}, not the whole character. "
	"Use null if it is not visible."
)
FACE = re.compile(r"\b(?:face|head|eyes?|expression|smil\w*|cheeks?|nose|mouth)\b", re.I)
PAW = re.compile(r"\b(?:paws?|hands?|fingers?)\b", re.I)
# The largest share of the wide drawing's height a crop may keep, so a loose box still
# yields a real close-up.
MAX_SHARE = {"close_up": 0.7, "extreme_close_up": 0.55}


def focus_target(opening):
	"""The short object name the observer is asked to locate for this close-up."""
	if PAW.search(opening):
		return "the character's paws together with the object they hold or touch"
	if FACE.search(opening):
		return "the character's face and head"
	return opening[:200]


def is_character_detail(shot):
	"""A close or extreme-close scene with a character: the model would draw it full-body."""
	from joymedia.services.planning.shot_structure import structure_for

	roles = {frappe.scrub(row.reference_role or "") for row in shot.get("generation_inputs") or []}
	return (structure_for(shot) or {}).get("framing") in CLOSE_FRAMINGS and bool(roles & CAST_ROLES)


def detail_scale(job, workflow):
	"""How much larger than the delivery size this task's picture is drawn."""
	if workflow.output_media_type != "Image" or not job.get("shot"):
		return 1
	return DETAIL_SCALE if is_character_detail(frappe.get_doc("Shot", job.shot)) else 1


def crop_window(size, box, target, max_share=1.0):
	"""A target-aspect window around ``box`` (pixels), never smaller than ``target``, inside ``size``.

	``max_share`` caps the window's height as a share of the picture's height.
	"""
	width, height = size
	target_width, target_height = target
	x1, y1, x2, y2 = box
	centre_x, centre_y = (x1 + x2) / 2, (y1 + y2) / 2
	aspect = target_width / target_height
	crop_height = max((y2 - y1) * FOCUS_MARGIN, (x2 - x1) * FOCUS_MARGIN / aspect, target_height)
	crop_height = min(crop_height, max(target_height, height * max_share), height, width / aspect)
	crop_width = crop_height * aspect
	left = min(max(0, centre_x - crop_width / 2), width - crop_width)
	top = min(max(0, centre_y - crop_height / 2), height - crop_height)
	return round(left), round(top), round(left + crop_width), round(top + crop_height)


def _focus_box(image_bytes, size, opening, ask):
	"""The focal region in full-size pixels, or None when the observer cannot place it."""
	from PIL import Image

	answer = ask(image_bytes, FOCUS.format(target=focus_target(opening)), max_edge=FOCUS_EDGE)
	box = answer.get("bbox_2d") if isinstance(answer, dict) else None
	if not isinstance(box, (list, tuple)) or len(box) != 4:
		return None
	try:
		x1, y1, x2, y2 = (float(value) for value in box)
	except (TypeError, ValueError):
		return None
	if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
		return None
	with Image.open(io.BytesIO(image_bytes)) as image:
		thumbnail = image.copy()
	thumbnail.thumbnail((FOCUS_EDGE, FOCUS_EDGE))
	scale_x, scale_y = size[0] / thumbnail.size[0], size[1] / thumbnail.size[1]
	x1, x2 = sorted((max(0, x1 * scale_x), min(size[0], x2 * scale_x)))
	y1, y2 = sorted((max(0, y1 * scale_y), min(size[1], y2 * scale_y)))
	if x2 - x1 < 8 or y2 - y1 < 8:
		return None
	return x1, y1, x2, y2


def crop_to_detail(attempt, image_bytes, *, ask=None):
	"""Crop a double-size close character frame to its focal region at the delivery size.

	Returns the bytes unchanged for every other picture. When the focal region
	cannot be placed, the whole picture is scaled down instead, and the normal
	framing check judges it.
	"""
	from PIL import Image

	job = frappe.get_doc("Generation Task", attempt.generation_task)
	workflow = frappe.get_doc("Generation Workflow", job.workflow)
	if detail_scale(job, workflow) == 1:
		return image_bytes
	snapshot = frappe.parse_json(
		frappe.db.get_value("Generation Run", job.generation_run, "project_snapshot_json") or "{}"
	)
	target = (int(snapshot["delivery_width"]), int(snapshot["delivery_height"]))
	with Image.open(io.BytesIO(image_bytes)) as image:
		size = image.size
		if size[0] <= target[0]:
			return image_bytes  # Drawn before this change, at the delivery size.
		shot = frappe.get_doc("Shot", job.shot)
		opening = str(shot.start_state or shot.image_prompt or "")
		if ask is None:
			from joymedia.services.review.consistency import ask
		box = _focus_box(image_bytes, size, opening, ask)
		from joymedia.services.planning.shot_structure import structure_for

		share = MAX_SHARE.get((structure_for(shot) or {}).get("framing"), 1.0)
		window = crop_window(size, box, target, share) if box else (0, 0, size[0], size[1])
		cropped = image.convert("RGB").crop(window).resize(target, Image.LANCZOS)
	frappe.logger("joymedia").info(
		"detail crop %s: %s -> %s from %s", attempt.name, size, window, "focus" if box else "whole frame"
	)
	output = io.BytesIO()
	cropped.save(output, format="PNG")
	return output.getvalue()
