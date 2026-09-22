# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

from typing import ClassVar

import frappe
from frappe import _
from frappe.model.document import Document


class MediaSpecification(Document):
	IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = ("media_project", "version_number")
	EXECUTION_CONTRACT_FIELDS: ClassVar[tuple[str, ...]] = (
		"workflow",
		"video_style",
		"total_duration_seconds",
		"delivery_preset",
		"delivery_width",
		"delivery_height",
		"generation_instructions",
	)
	PRESET_DIMENSIONS: ClassVar[dict[str, tuple[int, int]]] = {
		"Landscape": (1344, 768),
		"Portrait": (768, 1344),
		"Square": (1024, 1024),
	}

	def validate(self):
		self._resolve_generation_setup()
		self._validate_version_immutability()
		self._validate_timeline()
		self.validate_generation_setup()
		if self.delivery_preset in self.PRESET_DIMENSIONS:
			self.delivery_width, self.delivery_height = self.PRESET_DIMENSIONS[self.delivery_preset]
		elif self.delivery_preset == "Custom" and (
			self.delivery_width is None
			or self.delivery_height is None
			or self.delivery_width <= 0
			or self.delivery_height <= 0
		):
			frappe.throw("Custom delivery presets require a positive width and height")

	def _resolve_generation_setup(self):
		if self.workflow:
			return

		workflow = frappe.db.get_value(
			"Workflow",
			{
				"client_visible": 1,
				"is_active": 1,
				"status": ["in", ["Testing", "Production"]],
			},
			"name",
			order_by="version_number desc, modified desc",
		)
		if not workflow:
			frappe.throw(_("No default Workflow is configured."))
		self.workflow = workflow

	def validate_generation_setup(self):
		if self.status != "Ready":
			return

		if not self.workflow:
			frappe.throw(_("Ready Media Specifications require a Workflow."))

		workflow_version = frappe.get_doc(
			"Workflow",
			self.workflow,
		)

		if workflow_version.status not in ("Testing", "Production"):
			frappe.throw(
				_("Workflow {0} must be Testing or Production.").format(
					workflow_version.name
				)
			)


	def on_update(self):
		if self.has_value_changed("total_duration_seconds"):
			from joymedia.services.shot_duration_planner import recalculate_shot_durations

			recalculate_shot_durations(self.name)

	def _validate_timeline(self):
		if (self.total_duration_seconds or 0) <= 0:
			frappe.throw(_("Total Duration must be greater than zero."))
		if self.workflow:
			workflow_version = frappe.get_doc("Workflow", self.workflow)
			if (workflow_version.output_fps or 0) <= 0:
				frappe.throw(_("Workflow output FPS must be greater than zero."))

	def _validate_version_immutability(self):
		if self.is_new():
			return

		previous = self.get_doc_before_save()
		if not previous:
			return

		for fieldname in MediaSpecification.IDENTITY_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(_("Media Specification {0} cannot be changed after creation.").format(fieldname))

		if previous.status != "Draft" and self.status == "Draft":
			frappe.throw(_("A Ready, Superseded, or Archived Media Specification cannot return to Draft."))

		if not MediaSpecification._execution_has_started(self):
			return

		for fieldname in MediaSpecification.EXECUTION_CONTRACT_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(
					_("Execution contract field {0} cannot change after Generation Jobs or Runs exist.").format(
						fieldname
					)
				)

	def _execution_has_started(self):
		if frappe.db.exists("Generation Run", {"media_specification": self.name}):
			return True
		shot_names = frappe.get_all(
			"Shot Specification", filters={"media_specification": self.name}, pluck="name"
		)
		return bool(
			shot_names
			and frappe.db.exists("Generation Job", {"shot_specification": ["in", shot_names]})
		)
