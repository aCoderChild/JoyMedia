# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PromptTemplateVersion(Document):
	def validate(self):
		if not self.prompt_template or self.version_number is None:
			return

		filters = {"prompt_template": self.prompt_template, "version_number": self.version_number}
		if self.name:
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Prompt Template Version", filters):
			frappe.throw(_("Prompt Template Version Number must be unique within a Prompt Template."))
