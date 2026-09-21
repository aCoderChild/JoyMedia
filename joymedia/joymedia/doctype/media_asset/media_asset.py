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
				frappe.throw("Organization-scoped assets cannot belong to a Media Project")
		elif self.asset_scope == "Project":
			if not self.media_project:
				frappe.throw("Media Project is required for Project-scoped assets")

			project_organization = frappe.db.get_value(
				"Media Project",
				self.media_project,
				"client_organization",
			)
			if not project_organization:
				frappe.throw("Project-scoped assets require a Media Project with a Business")
			self.client_organization = project_organization
		else:
			frappe.throw("Asset Scope must be Organization or Project")

		if self.asset_category == "Shot Output" and self.media_type != "Video":
			frappe.throw("Shot Output assets must have media type Video")

		if self.asset_category == "Shot Output" and self.asset_scope != "Project":
			frappe.throw("Shot Output assets must be Project-scoped")
