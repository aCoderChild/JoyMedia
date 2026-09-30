# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MediaAsset(Document):
	def validate(self):
		self.asset_name = (self.asset_name or "").strip()
		if not self.asset_name:
			frappe.throw(_("Asset Name is required."))
		if not self.asset_scope:
			self.asset_scope = "Project Output" if self.media_project else "Library"
		if self.asset_scope == "Project Output" and not self.media_project:
			frappe.throw(_("Project Output assets require a Media Project."))
		if self.asset_scope == "Library" and self.media_project:
			frappe.throw(_("Library assets cannot belong directly to a project."))
