# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationJob(Document):
	def validate(self):
		if not self.requested_variants or self.requested_variants <= 0:
			frappe.throw(_("Requested Variants must be greater than zero."))
		self._validate_compiled_prompt_shot()
		self._validate_workflow_prompt_profile()

	def _validate_compiled_prompt_shot(self):
		if not self.shot_specification or not self.compiled_prompt:
			return

		compiled_prompt_shot = frappe.db.get_value(
			"Compiled Prompt", self.compiled_prompt, "shot_specification"
		)
		if compiled_prompt_shot != self.shot_specification:
			frappe.throw(
				_("Generation Job Shot Specification must match the Compiled Prompt Shot Specification.")
			)

	def _validate_workflow_prompt_profile(self):
		if not self.workflow_version or not self.compiled_prompt:
			return

		workflow_profile = frappe.db.get_value(
			"Workflow Version", self.workflow_version, "workflow_profile"
		)
		prompt_template_version = frappe.db.get_value(
			"Compiled Prompt", self.compiled_prompt, "prompt_template_version"
		)
		if not workflow_profile or not prompt_template_version:
			frappe.throw(_("Workflow and prompt template profiles must match."))

		prompt_template = frappe.db.get_value(
			"Prompt Template Version", prompt_template_version, "prompt_template"
		)
		if not prompt_template:
			frappe.throw(_("Workflow and prompt template profiles must match."))

		prompt_profile = frappe.db.get_value("Prompt Template", prompt_template, "workflow_profile")
		if workflow_profile != prompt_profile:
			frappe.throw(_("Workflow and prompt template profiles must match."))

	def validate_for_execution(self):
		self.validate()
		shot = frappe.get_doc("Shot Specification", self.shot_specification)
		workflow_version = frappe.get_doc("Workflow Version", self.workflow_version)

		if workflow_version.status not in ("Testing", "Production"):
			frappe.throw(
				_("Workflow Version {0} must be Testing or Production.").format(workflow_version.name)
			)

		required_roles = {
			binding.required_input_role
			for binding in workflow_version.bindings
			if binding.value_source == "Generation Input" and binding.required and binding.required_input_role
		}
		for role in required_roles:
			inputs = frappe.get_all(
				"Generation Input",
				filters={"generation_job": self.name, "input_role": role},
				fields=["asset_version"],
			)
			usable_inputs = [
				row
				for row in inputs
				if frappe.db.get_value("Asset Version", row.asset_version, "file")
			]
			if len(usable_inputs) != 1:
				frappe.throw(
					_("Generation Job {0} requires exactly one usable input with role '{1}'.").format(
						self.name, role
					)
				)
