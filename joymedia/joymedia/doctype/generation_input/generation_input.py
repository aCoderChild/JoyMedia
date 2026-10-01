# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationInput(Document):
	"""One frozen input row owned by a Generation Task."""

	def validate(self):
		if not self.input_role:
			frappe.throw(_("Generation Input requires an Input Role."))
		if bool(self.asset_version) == bool(self.generation_artifact):
			frappe.throw(
				_("Generation Input must reference exactly one Asset Version or Generation Artifact.")
			)
