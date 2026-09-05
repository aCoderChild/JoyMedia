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
		self._validate_unique_version_number()
		self._validate_generation_setup()
		if self.delivery_preset in self.PRESET_DIMENSIONS:
			self.delivery_width, self.delivery_height = self.PRESET_DIMENSIONS[self.delivery_preset]
		elif self.delivery_preset == "Custom" and (
			self.delivery_width is None
			or self.delivery_height is None
			or self.delivery_width <= 0
			or self.delivery_height <= 0
		):
			frappe.throw("Custom delivery presets require a positive width and height")

	def _validate_unique_version_number(self):
		if not self.media_project or self.version_number is None:
			return

		filters = {"media_project": self.media_project, "version_number": self.version_number}
		if self.name:
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Media Specification", filters):
			frappe.throw("Media Specification Version Number must be unique within a Media Project.")

	def _validate_generation_setup(self):
		if self.status == "Ready" and (
			not self.generation_workflow_version or not self.prompt_template_version
		):
			frappe.throw(
				"Generation Workflow Version and Prompt Template Version are required when Media Specification is Ready."
			)

		if not self.generation_workflow_version or not self.prompt_template_version:
			return

		workflow_profile = frappe.db.get_value(
			"Workflow Version", self.generation_workflow_version, "workflow_profile"
		)
		prompt_template = frappe.db.get_value(
			"Prompt Template Version", self.prompt_template_version, "prompt_template"
		)
		if not workflow_profile or not prompt_template:
			frappe.throw("Workflow and prompt template profiles must match.")

		prompt_profile = frappe.db.get_value("Prompt Template", prompt_template, "workflow_profile")
		if workflow_profile != prompt_profile:
			frappe.throw("Workflow and prompt template profiles must match.")
