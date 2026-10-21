"""Authored delivery geometry, independent of provider grids and media presets."""

import math
import re
from fractions import Fraction

PRESET_RATIOS = {"Landscape": (16, 9), "Portrait": (9, 16), "Square": (1, 1)}


def parse_ratio(text):
	"""Read the first declared ratio/dimensions; never infer a platform's shape."""
	value = str(text or "").strip()
	if value in PRESET_RATIOS:
		return PRESET_RATIOS[value]
	match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[:x×]\s*(\d+(?:\.\d+)?)(?!\d|\.\d)", value)
	if not match:
		return None
	width, height = map(Fraction, match.groups())
	if width <= 0 or height <= 0:
		raise ValueError("Aspect ratio dimensions must be positive.")
	ratio = width / height
	return ratio.numerator, ratio.denominator


def orientation(ratio):
	width, height = ratio
	return "Portrait" if width < height else "Square" if width == height else "Landscape"


def ratio_label(width, height):
	if not width or not height:
		return ""
	width, height = int(width), int(height)
	if width <= 0 or height <= 0:
		raise ValueError("Delivery dimensions must be positive.")
	divisor = math.gcd(width, height)
	return f"{width // divisor}:{height // divisor}"


def delivery_dimensions(ratio, short_edge):
	"""Preserve the exact rational aspect with even dimensions for video encoding."""
	width, height = ratio
	if min(width, height) <= 0:
		raise ValueError("Aspect ratio dimensions must be positive.")
	# Use a shared even multiplier, rather than rounding each axis independently.
	scale = max(2, round(float(short_edge) / min(width, height) / 2) * 2)
	return width * scale, height * scale


def require_dimensions(snapshot):
	width, height = snapshot.get("delivery_width"), snapshot.get("delivery_height")
	if not width or not height or int(width) <= 0 or int(height) <= 0:
		raise ValueError("Specify the video's aspect ratio before generation.")
	return int(width), int(height)


def composition_instruction(project):
	"""Describe the authored active picture, independently of a provider's grid."""
	ratio = ratio_label(project.get("delivery_width"), project.get("delivery_height"))
	if not ratio:
		return ""
	return (
		f"Compose the scene for the full {ratio} delivery canvas. "
		"The continuous environment fills the entire frame edge to edge throughout the shot, "
		"including above and below the subject. Shot size describes subject coverage within this canvas, "
		"not a different screen shape. Keep the active picture full frame without letterboxing, "
		"pillarboxing, borders or an inset landscape picture."
	)


def duration_from_description(text):
	"""Read a duration only with a time unit, never the first number in an aspect."""
	match = re.search(
		r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*(?:-\s*)?(?:seconds?\b|secs?\b|s\b|giây\b)", str(text or ""), re.I
	)
	return float(match.group(1).replace(",", ".")) if match else None
