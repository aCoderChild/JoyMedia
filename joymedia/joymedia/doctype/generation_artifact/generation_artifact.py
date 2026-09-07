# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


IDENTITY_FIELDS = (
	"artifact_key",
	"generation_attempt",
	"remote_filename",
	"remote_subfolder",
	"remote_file_type",
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
		if previous.lifecycle_status == "Deleted" and self.lifecycle_status != "Deleted":
			frappe.throw(_("Deleted Generation Artifacts are terminal."))
		if previous.lifecycle_status == "Expired" and self.lifecycle_status == "Temporary":
			frappe.throw(_("Expired Generation Artifacts cannot return to Temporary."))

		for fieldname in IDENTITY_FIELDS:
			if (self.get(fieldname) or "") != (previous.get(fieldname) or ""):
				frappe.throw(_("Generation Artifact {0} cannot be changed after creation.").format(fieldname))
