# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class WorkflowProfile(Document):
	def validate(self):
		self._validate_default_workflow_version()
		self._validate_default_prompt_template_version()

	def _validate_default_workflow_version(self):
		if not self.default_workflow_version:
			return

		workflow_profile = frappe.db.get_value(
			"Workflow Version",
			self.default_workflow_version,
			"workflow_profile",
		)

		if workflow_profile != self.name:
			frappe.throw(_("Default Workflow Version must belong to this Workflow Profile."))

	def _validate_default_prompt_template_version(self):
		if not self.default_prompt_template_version:
			return

		prompt_template = frappe.db.get_value(
			"Prompt Template Version",
			self.default_prompt_template_version,
			"prompt_template",
		)
		prompt_profile = frappe.db.get_value(
			"Prompt Template",
			prompt_template,
			"workflow_profile",
		)

		if prompt_profile != self.name:
			frappe.throw(
				_("Default Prompt Template Version must belong to this Workflow Profile.")
			)
