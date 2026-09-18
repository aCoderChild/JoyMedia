# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import base64
import mimetypes
from pathlib import Path

import frappe
from frappe import _
from frappe.model.document import Document


ALLOWED_STATUSES = {
	"Draft",
	"Generating",
	"Review",
	"Completed",
	"Needs Attention",
	"Cancelled",
}


class MediaProject(Document):
	def before_insert(self):
		self.status = "Draft"

	def validate(self):
		self.project_name = (self.project_name or "").strip()
		self.product_name = (self.product_name or "").strip()
		self.target_audience = (self.target_audience or "").strip()

		if not self.project_name:
			frappe.throw(_("Project Name is required."))

		if not self.product_name:
			frappe.throw(_("Product Name is required."))

		if not self.target_audience:
			frappe.throw(_("Target Audience is required."))

		if self.status not in ALLOWED_STATUSES:
			frappe.throw(_("Invalid Media Project status."))

	@frappe.whitelist()
	def generate_video_plan(self):
		from joymedia.services.qwen_client import generate_video_plan

		template = None
		if self.reference_template:
			ref = frappe.get_doc("Video Reference Template", self.reference_template)
			template = frappe.parse_json(ref.template_json)

		return generate_video_plan(
			product_name=self.product_name,
			target_audience=self.target_audience,
			video_idea=self.video_idea,
			reference_template=template,
			reference_images=self._get_project_image_inputs(),
		)

	def _get_project_image_inputs(self):
		media_assets = frappe.get_all(
			"Media Asset",
			filters={
				"media_project": self.name,
				"media_type": "Image",
				"status": "Active",
			},
			fields=["name", "asset_name"],
			order_by="asset_name asc, name asc",
		)
		if not media_assets:
			return []

		asset_versions = frappe.get_all(
			"Asset Version",
			filters={"media_asset": ["in", [asset.name for asset in media_assets]]},
			fields=["name", "media_asset", "version_number", "file"],
			order_by="media_asset asc, version_number desc",
		)
		latest_versions = {}
		for version in asset_versions:
			latest_versions.setdefault(version.media_asset, version)

		reference_images = []
		for asset in media_assets:
			version = latest_versions.get(asset.name)
			if not version:
				continue

			if not version.file:
				frappe.throw(_("Asset Version {0} has no image file.").format(version.name))

			file_doc = frappe.get_doc("File", {"file_url": version.file})
			file_path = Path(file_doc.get_full_path())
			if not file_path.exists():
				frappe.throw(_("Asset Version file does not exist: {0}").format(version.file))

			mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
			encoded_file = base64.b64encode(file_path.read_bytes()).decode("ascii")
			reference_images.append(
				{
					"index": len(reference_images) + 1,
					"media_asset": asset.name,
					"asset_name": asset.asset_name,
					"asset_version": version.name,
					"data_url": f"data:{mime_type};base64,{encoded_file}",
				}
			)

		return reference_images
