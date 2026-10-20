"""Every tunable number of the keyframe, paste and audio steps, in one place.

Defaults were measured on rendered clips; a site overrides any of them in site_config.json under
"joymedia_tuning", for example {"character_height": 0.45, "effects_flatness_min": 0.35}. Unknown keys are ignored.
"""

import frappe

DEFAULTS = {
	# Paste layout (fractions of the canvas)
	"character_height": 0.36, "character_width": 0.70, "character_baseline": 0.86,
	"product_height": 0.15, "product_width": 0.40, "product_baseline": 0.90,
	# A product with no character in the frame is the hero: it is drawn larger.
	"hero_product_height": 0.42, "hero_product_width": 0.55,
	# On the closing scene the product is the biggest thing in the picture, in front of the cast at the sides.
	"closing_product_height": 0.42, "closing_product_width": 0.62,
	"closing_side_product_scale": 0.5, "closing_side_product_offset": 0.25, "closing_side_product_lift": 0.05,
	# The cast stands at the outer edges a little further back than the products, at its normal size.
	"closing_character_scale": 1.0, "closing_character_edge": 0.17, "closing_character_baseline": 0.80,
	# In front of drawn characters the product stands on the floor in the lower middle, at an everyday size.
	"front_product_height": 0.17, "front_product_width": 0.34, "front_product_baseline": 0.95,
	# The real pack is laid over a video frame only while the frame's pack region stays this close (mean grey 0-255)
	# to the first frame's; beyond it the camera moved and the frame is left as rendered.
	"pack_lock_tolerance": 18,
	"product_near": 0.03, "product_offset": 0.22, "edge_margin": 0.02,
	"colour_match": 0.16,
	# A cutout counts as transparent when its least opaque pixel is below this alpha (0-255).
	"opaque_below": 250,
	# Audio screen: spectral flatness of the audible parts (0 tonal ... 1 noise).
	"effects_flatness_min": 0.40, "effects_layer_accept_min": 0.15, "effects_borderline_max": 0.50, "effect_layer_attempts": 3,
}


def tune(key):
	"""The site's value for a tunable, else its default."""
	overrides = frappe.conf.get("joymedia_tuning") or {}
	return overrides.get(key, DEFAULTS[key]) if isinstance(overrides, dict) else DEFAULTS[key]
