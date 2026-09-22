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

		if (self.requested_variants_per_shot or 0) < 1:
			frappe.throw(_("Requested Variants Per Shot must be greater than zero."))
		if (self.max_retries or 0) < 0:
			frappe.throw(_("Max Retries cannot be negative."))
