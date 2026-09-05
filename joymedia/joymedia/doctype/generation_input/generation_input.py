# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationInput(Document):
	def validate(self):
		if not self.generation_job or not self.asset_version:
			return

		job = frappe.get_doc("Generation Job", self.generation_job)
		shot = frappe.get_doc("Shot Specification", job.shot_specification)
		media_specification = frappe.get_doc("Media Specification", shot.media_specification)
		media_project = frappe.get_doc("Media Project", media_specification.media_project)
		asset_version = frappe.get_doc("Asset Version", self.asset_version)
		media_asset = frappe.get_doc("Media Asset", asset_version.media_asset)

		if media_asset.asset_scope == "Project":
			if media_asset.media_project != media_project.name:
				frappe.throw(
					_("Project-scoped Asset Version must belong to the Generation Job's Media Project.")
				)
		elif media_asset.asset_scope == "Organization":
			if (
				not media_project.client_organization
				or media_asset.client_organization != media_project.client_organization
			):
				frappe.throw(
					_("Organization-scoped Asset Version must belong to the Generation Job's Client Organization.")
				)
		else:
			frappe.throw(_("Media Asset scope must be Project or Organization."))
