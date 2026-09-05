# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MediaAsset(Document):
	def validate(self):
		if self.asset_scope == "Organization" and not self.client_organization:
			frappe.throw("Client Organization is required for Organization-scoped assets")

		if self.asset_scope == "Project" and not self.media_project:
			frappe.throw("Media Project is required for Project-scoped assets")
