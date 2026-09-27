# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MediaAsset(Document):
	def validate(self):
		if not self.library_visibility:
			self.library_visibility = "Internal" if self.asset_category in {"Shot Output", "Storyboard"} else "Visible"

		if not self.client_organization:
			frappe.throw("Client Organization is required for every Media Asset")

		if self.campaign:
			campaign_organization = frappe.db.get_value("Campaign", self.campaign, "client_organization")
			if not campaign_organization:
				frappe.throw("Media Asset origin requires a valid Campaign")
			if campaign_organization != self.client_organization:
				frappe.throw("Media Asset and Campaign must belong to the same Client Organization")

		if self.media_project:
			project_organization = frappe.db.get_value("Media Project", self.media_project, "client_organization")
			if not project_organization:
				frappe.throw("Media Asset origin requires a valid Media Project")
			if project_organization != self.client_organization:
				frappe.throw("Media Asset and Media Project must belong to the same Client Organization")

		if self.asset_category == "Shot Output" and self.media_type != "Video":
			frappe.throw("Shot Output assets must have media type Video")
