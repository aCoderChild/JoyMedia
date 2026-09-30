# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

class GenerationRun(Document):
	def validate(self):
		media_specification = frappe.get_doc("Media Specification", self.media_specification)
		if not self.workflow_version:
			self.workflow_version = media_specification.workflow

		if self.workflow_version != media_specification.workflow:
			frappe.throw(
				_("Generation Run Workflow must match the Media Specification Workflow.")
			)
