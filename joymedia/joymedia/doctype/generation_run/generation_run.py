# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

class GenerationRun(Document):
	def validate(self):
		project = frappe.get_doc("Media Project", self.media_project)
		if not self.workflow:
			self.workflow = project.workflow
