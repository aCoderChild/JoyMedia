# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from joymedia.services.execution_router import get_model_cache_key


class GenerationRun(Document):
	def validate(self):
		media_specification = frappe.get_doc("Media Specification", self.media_specification)
		if self.workflow_version != media_specification.generation_workflow_version:
			frappe.throw(
				_("Generation Run Workflow Version must match the Media Specification Workflow Version.")
			)

		self.model_cache_key = get_model_cache_key(self.workflow_version)
