# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

from typing import ClassVar

import frappe
from frappe.model.document import Document


class MediaSpecification(Document):
	PRESET_DIMENSIONS: ClassVar[dict[str, tuple[int, int]]] = {
		"Landscape 720p": (1280, 720),
		"Landscape 1080p": (1920, 1080),
		"Portrait 720p": (720, 1280),
		"Portrait 1080p": (1080, 1920),
		"Square 1080p": (1080, 1080),
	}

	def validate(self):
		if self.aspect_ratio in self.PRESET_DIMENSIONS:
			self.delivery_width, self.delivery_height = self.PRESET_DIMENSIONS[self.aspect_ratio]
		elif self.aspect_ratio == "Custom" and (
			self.delivery_width is None
			or self.delivery_height is None
			or self.delivery_width <= 0
			or self.delivery_height <= 0
		):
			frappe.throw("Custom delivery presets require a positive width and height")
