# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationInput(Document):
	def validate(self):
		if not self.generation_job:
			frappe.throw(_("Generation Input requires a Generation Job."))
		if not self.input_role:
			frappe.throw(_("Generation Input requires an Input Role."))
		if not self.asset_version and not self.generation_artifact:
			frappe.throw(_("Generation Input requires an Asset Version or Generation Artifact."))
		if self.asset_version and self.generation_artifact:
			frappe.throw(_("Generation Input cannot reference both an Asset Version and Generation Artifact."))

		if self.is_new():
			return
		if frappe.db.exists("Generation Attempt", {"generation_job": self.generation_job}):
			previous = frappe.db.get_value(
				"Generation Input",
				self.name,
				["generation_job", "input_role", "asset_version", "generation_artifact"],
				as_dict=True,
			)
			if previous and any(
				(self.get(fieldname) or "") != (previous.get(fieldname) or "")
				for fieldname in ("generation_job", "input_role", "asset_version", "generation_artifact")
			):
				frappe.throw(_("Generation Input {0} is immutable after execution begins.").format(self.name))
