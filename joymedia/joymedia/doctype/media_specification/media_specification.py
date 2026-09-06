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
		if self.delivery_preset in self.PRESET_DIMENSIONS:
			self.delivery_width, self.delivery_height = self.PRESET_DIMENSIONS[self.delivery_preset]
		elif self.delivery_preset == "Custom" and (
			self.delivery_width is None
			or self.delivery_height is None
			or self.delivery_width <= 0
			or self.delivery_height <= 0
		):
			frappe.throw("Custom delivery presets require a positive width and height")

		self._validate_workflow_delivery_orientation()

	def _validate_workflow_delivery_orientation(self):
		"""Reject a workflow whose configured execution orientation contradicts delivery."""
		if not (
			self.generation_workflow_version
			and self.delivery_width
			and self.delivery_height
		):
			return

		workflow_dimensions = frappe.db.get_value(
			"Workflow Version",
			self.generation_workflow_version,
			["execution_width", "execution_height"],
			as_dict=True,
		)
		if not (
			workflow_dimensions
			and workflow_dimensions.execution_width
			and workflow_dimensions.execution_height
		):
			return

		delivery_orientation = (self.delivery_width > self.delivery_height) - (
			self.delivery_width < self.delivery_height
		)
		execution_orientation = (
			workflow_dimensions.execution_width > workflow_dimensions.execution_height
		) - (workflow_dimensions.execution_width < workflow_dimensions.execution_height)
		if delivery_orientation != execution_orientation:
			frappe.throw(
			"Generation Workflow Version execution dimensions must have the same orientation "
			"as the Media Specification delivery dimensions."
			)
