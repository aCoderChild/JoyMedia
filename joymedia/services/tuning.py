"""Every tunable number of the keyframe, paste and audio steps, in one place.

Defaults were measured on rendered clips; a site overrides any of them in site_config.json under
"joymedia_tuning", for example {"character_height": 0.45, "effects_flatness_min": 0.35}. Unknown keys are ignored.
"""

import frappe

DEFAULTS = {
	# Paste layout (fractions of the canvas)
	"character_height": 0.36, "character_width": 0.70, "character_baseline": 0.86,
	"product_height": 0.15, "product_width": 0.40, "product_baseline": 0.90,
	"product_near": 0.03, "product_offset": 0.22, "edge_margin": 0.02,
	"logo_max_width": 0.22, "logo_max_height": 0.08, "logo_margin": 0.04,
	"colour_match": 0.16,
	# A cutout counts as transparent when its least opaque pixel is below this alpha (0-255).
	"opaque_below": 250,
	# Audio screen: spectral flatness of the audible parts (0 tonal ... 1 noise).
	"effects_flatness_min": 0.40, "effects_borderline_max": 0.50, "effect_layer_attempts": 3,
}


def tune(key):
	"""The site's value for a tunable, else its default."""
	overrides = frappe.conf.get("joymedia_tuning") or {}
	return overrides.get(key, DEFAULTS[key]) if isinstance(overrides, dict) else DEFAULTS[key]
