# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

"""Single source of truth for generation-mode and reference-mode resolution.

These were previously copy-pasted across the controller, the Qwen client and the
video-plan service, which let them drift. Keep all normalization here.
"""

GENERATION_MODE_ALIASES = {
	"Independent": "Multi-shot",
	"Chained": "Continuous",
	"Consistency": "Continuous",
}
DEFAULT_GENERATION_MODE = "Continuous"


def normalize_generation_mode(value):
	"""Map legacy generation-mode names onto the two canonical values."""
	return GENERATION_MODE_ALIASES.get(value, value or DEFAULT_GENERATION_MODE)


def detect_reference_mode(reference_count):
	"""Pick the reference mode from how many image references are available.

	Two or more references feed the Reference-to-Video workflow (person + place);
	a single reference drives Image-to-Video.
	"""
	return "Multi-reference" if int(reference_count or 0) >= 2 else "Single Image"
