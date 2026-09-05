# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MediaAsset(Document):
	def validate(self):
		if self.asset_scope == "Organization":
			if not self.client_organization:
				frappe.throw("Client Organization is required for Organization-scoped assets")
			if self.media_project:
				frappe.throw("Organization-scoped assets cannot be linked to a Media Project")
		elif self.asset_scope == "Project":
			if not self.media_project:
				frappe.throw("Media Project is required for Project-scoped assets")
			self.client_organization = frappe.db.get_value(
				"Media Project", self.media_project, "client_organization"
			)
		else:
			frappe.throw("Asset Scope must be Organization or Project")
