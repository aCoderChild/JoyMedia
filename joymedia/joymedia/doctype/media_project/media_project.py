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

		if not self.client_organization:
			frappe.throw(_("Business is required."))

		if self.status not in ALLOWED_STATUSES:
			frappe.throw(_("Invalid Media Project status."))

	@frappe.whitelist()
	def generate_video_plan(self, media_specification_name, scene_count):
		from joymedia.services.qwen_client import generate_video_plan

		media_specification = frappe.get_doc("Media Specification", media_specification_name)
		if media_specification.media_project != self.name:
			frappe.throw(_("Media Specification must belong to this Media Project."))
		if media_specification.status != "Draft":
			frappe.throw(_("Video plans can only be generated for Draft Media Specifications."))
		if not media_specification.generation_workflow_version:
			frappe.throw(_("Media Specification must have a Generation Workflow Version."))

		workflow_version = frappe.get_doc(
			"Workflow Version",
			media_specification.generation_workflow_version,
		)

		try:
			scene_count = int(scene_count)
		except (TypeError, ValueError):
			frappe.throw(_("Number of Scenes must be a positive integer."))
		if scene_count < 1:
			frappe.throw(_("Number of Scenes must be at least 1."))

		template = None
		if self.reference_template:
			ref = frappe.get_doc("Video Reference Template", self.reference_template)
			template = frappe.parse_json(ref.template_json)

		return generate_video_plan(
			product_name=self.product_name,
			target_audience=self.target_audience,
			video_idea=self.video_idea,
			total_video_duration=media_specification.total_duration_seconds,
			target_fps=workflow_version.output_fps,
			scene_count=scene_count,
			reference_template=template,
			reference_images=self._get_project_image_inputs(),
		)

	@frappe.whitelist()
	def generate_video(self, media_specification_name):
		from joymedia.services.generation_orchestrator import start_run

		media_specification = frappe.get_doc("Media Specification", media_specification_name)
		if media_specification.media_project != self.name:
			frappe.throw(_("Media Specification must belong to this Media Project."))
		if media_specification.status != "Draft":
			frappe.throw(_("Video generation can only start from a Draft Media Specification."))
		if not frappe.db.exists("Shot Specification", {"media_specification": media_specification.name}):
			frappe.throw(_("Apply a video plan before generating the video."))

		media_specification.status = "Ready"
		media_specification.save(ignore_permissions=True)

		run = frappe.get_doc(
			{
				"doctype": "Generation Run",
				"media_specification": media_specification.name,
				"requested_by": frappe.session.user,
				"requested_variants_per_shot": 1,
				"max_retries": 0,
				"auto_compose": 1,
				"status": "Draft",
			}
		).insert(ignore_permissions=True)

		result = start_run(run.name)
		frappe.db.commit()
		return {"run": run.name, "status": result["status"]}

	def _get_project_image_inputs(self):
		from joymedia.services.project_image_manifest import get_project_image_manifest

		return get_project_image_manifest(self.name, include_data_url=True)
