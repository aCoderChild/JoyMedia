# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

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
		from joymedia.services.project_image_manifest import get_project_image_manifest

		return get_project_image_manifest(self.name, include_data_url=True)
