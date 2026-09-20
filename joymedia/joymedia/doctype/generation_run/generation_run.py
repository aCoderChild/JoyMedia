# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

class GenerationRun(Document):
	def validate(self):
		media_specification = frappe.get_doc("Media Specification", self.media_specification)
		if not self.workflow_version:
			self.workflow_version = media_specification.generation_workflow_version

		if self.workflow_version != media_specification.generation_workflow_version:
			frappe.throw(
				_("Generation Run Workflow Version must match the Media Specification Workflow Version.")
			)

		workflow_version = frappe.get_doc("Workflow Version", self.workflow_version)
		self.model_cache_key = (workflow_version.model_cache_key or "").strip() or workflow_version.name
		if (self.requested_variants_per_shot or 0) < 1:
			frappe.throw(_("Requested Variants Per Shot must be greater than zero."))
		if (self.max_retries or 0) < 0:
			frappe.throw(_("Max Retries cannot be negative."))
