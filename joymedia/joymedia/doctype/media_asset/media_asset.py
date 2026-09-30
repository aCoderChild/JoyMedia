# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


OUTPUT_CATEGORIES = {"Shot Output", "Final Deliverable"}


class MediaAsset(Document):
	def validate(self):
		self.asset_name = (self.asset_name or "").strip()
		if not self.asset_name:
			frappe.throw(_("Asset Name is required."))

		if self.asset_category in OUTPUT_CATEGORIES:
			if self.media_type != "Video":
				frappe.throw(_("Generated outputs must be Video assets."))
			if not self.media_project:
				frappe.throw(_("Generated outputs require a Media Project."))
		elif self.media_project:
			frappe.throw(_("Only generated output assets may belong directly to a project."))
