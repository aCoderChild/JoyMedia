# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


IDENTITY_FIELDS = (
	"artifact_key",
	"generation_attempt",
	"media_type",
)


class GenerationArtifact(Document):

	def validate(self):
		if self.lifecycle_status == "Promoted" and not self.promoted_asset_version:
			frappe.throw(_("Promoted Generation Artifacts require a Promoted Asset Version."))
		if self.is_new():
			return

		previous = frappe.db.get_value(
			"Generation Artifact",
			self.name,
			["lifecycle_status", *IDENTITY_FIELDS],
			as_dict=True,
		)
		if not previous:
			return
		for fieldname in IDENTITY_FIELDS:
			if (self.get(fieldname) or "") != (previous.get(fieldname) or ""):
				frappe.throw(_("Generation Artifact {0} cannot be changed after creation.").format(fieldname))
