# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationAttempt(Document):
	def validate(self):
		if not self.generation_job or self.attempt_number is None:
			return

		filters = {"generation_job": self.generation_job, "attempt_number": self.attempt_number}
		if self.name:
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Generation Attempt", filters):
			frappe.throw(_("Attempt Number must be unique within a Generation Job."))

	def before_insert(self):
		if self.seed is None or self.seed == "":
			self.seed = str(secrets.randbelow(2**63))

		latest_attempt = frappe.db.get_value(
			"Generation Attempt",
			{"generation_job": self.generation_job},
			[{"MAX": "attempt_number"}],
		)
		self.attempt_number = (latest_attempt or 0) + 1
