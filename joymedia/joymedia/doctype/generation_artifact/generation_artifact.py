# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


IDENTITY_FIELDS = (
	"artifact_key",
	"artifact_role",
	"generation_attempt",
	"media_type",
	"provider_locator",
)


class GenerationArtifact(Document):

	def validate(self):
		if not self.artifact_role:
			frappe.throw(_("Artifact Role is required."))
		if self.is_new():
			return

		previous = frappe.db.get_value(
			"Generation Artifact",
			self.name,
			IDENTITY_FIELDS,
			as_dict=True,
		)
		if not previous:
			return
		for fieldname in IDENTITY_FIELDS:
			if (self.get(fieldname) or "") != (previous.get(fieldname) or ""):
				frappe.throw(_("Generation Artifact {0} cannot be changed after creation.").format(fieldname))
