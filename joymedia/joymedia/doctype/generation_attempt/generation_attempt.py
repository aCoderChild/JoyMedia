# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationAttempt(Document):
	def before_insert(self):
		job = frappe.get_doc("Generation Job", self.generation_job)
		if job.status != "Queued":
			frappe.throw(
				_("Generation Job {0} must be Queued before a Generation Attempt can be created.").format(
					self.generation_job
				)
			)
		job.validate_for_execution()
