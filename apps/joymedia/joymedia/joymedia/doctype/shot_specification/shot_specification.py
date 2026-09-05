# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ShotSpecification(Document):
	def validate(self):
		if not self.media_specification or self.shot_number is None:
			return

		filters = {"media_specification": self.media_specification, "shot_number": self.shot_number}
		if self.name:
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Shot Specification", filters):
			frappe.throw(_("Shot Number must be unique within a Media Specification."))
		self._validate_generation_inputs()

	def _validate_generation_inputs(self):
		media_specification = frappe.get_doc("Media Specification", self.media_specification)
		if media_specification.status != "Ready" or not media_specification.generation_workflow_version:
			return

		workflow_version = frappe.get_doc(
			"Workflow Version", media_specification.generation_workflow_version
		)
		input_roles = {
			binding.required_input_role
			for binding in workflow_version.bindings
			if binding.value_source == "Generation Input" and binding.required_input_role
		}
		required_roles = {
			binding.required_input_role
			for binding in workflow_version.bindings
			if binding.value_source == "Generation Input" and binding.required and binding.required_input_role
		}
		mapping_counts = {}
		for mapping in self.generation_inputs or []:
			if mapping.input_role not in input_roles:
				frappe.throw(_("Shot Input Mapping role is not defined by the configured Workflow Version."))
			mapping_counts[mapping.input_role] = mapping_counts.get(mapping.input_role, 0) + 1

		for role in required_roles:
			if mapping_counts.get(role) != 1:
				frappe.throw(
					_("Shot Specification requires exactly one Generation Input mapping for role '{0}'.").format(
						role
					)
				)
