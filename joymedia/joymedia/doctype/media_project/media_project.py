# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.synchronization import filelock


ALLOWED_STATUSES = {
	"Draft",
	"Generating",
	"Review",
	"Completed",
	"Needs Attention",
	"Cancelled",
}
H3_WORKFLOW_CODE = "MINIMAX-H3"


def get_latest_media_specification(media_project):
	specifications = frappe.get_all(
		"Media Specification",
		filters={"media_project": media_project},
		fields=["name", "version_number", "status"],
		order_by="version_number desc",
		limit=1,
	)
	if not specifications:
		return None

	return frappe.get_doc("Media Specification", specifications[0].name)


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
	def get_video_settings(self):
		media_specification = get_latest_media_specification(self.name)
		if not media_specification:
			return None

		return {
			"name": media_specification.name,
			"version_number": media_specification.version_number,
			"status": media_specification.status,
			"total_duration_seconds": media_specification.total_duration_seconds,
			"delivery_preset": media_specification.delivery_preset,
		}

	@frappe.whitelist()
	def save_video_settings(self, total_duration_seconds, delivery_preset):
		try:
			total_duration_seconds = float(total_duration_seconds)
		except (TypeError, ValueError):
			frappe.throw(_("Duration must be greater than zero."))

		if total_duration_seconds <= 0:
			frappe.throw(_("Duration must be greater than zero."))
		if delivery_preset not in ("Landscape", "Portrait", "Square"):
			frappe.throw(_("Select Landscape, Portrait, or Square format."))

		with filelock(f"joymedia-video-settings-{self.name}"):
			latest = get_latest_media_specification(self.name)
			if latest and latest.status != "Draft":
				frappe.throw(
					_(
						"Video Settings cannot be changed after generation starts. "
						"Use Revise Storyboard first."
					)
				)

			workflow_profile = frappe.db.get_value(
				"Workflow Profile",
				{"workflow_code": H3_WORKFLOW_CODE, "status": "Active"},
				"name",
			)
			if not workflow_profile:
				frappe.throw(
					_("No active MiniMax H3 Workflow Profile is configured.")
				)

			if latest:
				latest.total_duration_seconds = total_duration_seconds
				latest.delivery_preset = delivery_preset
				latest.save(ignore_permissions=True)
				media_specification = latest
			else:
				media_specification = frappe.get_doc(
					{
						"doctype": "Media Specification",
						"media_project": self.name,
						"version_number": 1,
						"status": "Draft",
						"workflow_profile": workflow_profile,
						"total_duration_seconds": total_duration_seconds,
						"delivery_preset": delivery_preset,
					}
				).insert(ignore_permissions=True)

		frappe.db.set_value("Media Project", self.name, "status", "Draft", update_modified=False)
		frappe.db.commit()
		return {
			"media_specification": media_specification.name,
			"version_number": media_specification.version_number,
			"total_duration_seconds": media_specification.total_duration_seconds,
			"delivery_preset": media_specification.delivery_preset,
		}

	@frappe.whitelist()
	def generate_video_plan(self, scene_count):
		from joymedia.services.qwen_client import generate_video_plan

		media_specification = get_latest_media_specification(self.name)
		if not media_specification:
			frappe.throw(_("Create Video Settings before generating a storyboard."))
		if media_specification.status != "Draft":
			frappe.throw(_("The current Campaign revision is not editable."))
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
	def generate_video(self):
		from joymedia.services.generation_orchestrator import start_run

		with filelock(f"joymedia-generate-video-{self.name}"):
			media_specification = get_latest_media_specification(self.name)
			if not media_specification:
				frappe.throw(_("This Campaign has no Video Settings."))

			media_specification.reload()
			existing_run = frappe.db.get_value(
				"Generation Run",
				{"media_specification": media_specification.name},
				["name", "status"],
				as_dict=True,
			)
			if existing_run:
				return {"run": existing_run.name, "status": existing_run.status}
			if media_specification.status != "Draft":
				frappe.throw(_("This Campaign revision has already been submitted."))
			if not frappe.db.exists(
				"Shot Specification", {"media_specification": media_specification.name}
			):
				frappe.throw(_("Generate and apply a storyboard first."))
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

	@frappe.whitelist()
	def apply_video_plan(self, plan_json):
		from joymedia.services.video_plan_service import apply_video_plan_from_ui

		media_specification = get_latest_media_specification(self.name)
		if not media_specification:
			frappe.throw(_("Create Video Settings before applying a storyboard."))

		return apply_video_plan_from_ui(
			media_specification_name=media_specification.name,
			plan_json=plan_json,
		)

	@frappe.whitelist()
	def create_storyboard_revision(self):
		with filelock(f"joymedia-storyboard-revision-{self.name}"):
			latest = get_latest_media_specification(self.name)
			if not latest:
				frappe.throw(_("This Campaign has no Video Settings to revise."))
			if latest.status == "Draft":
				frappe.db.set_value("Media Project", self.name, "status", "Draft", update_modified=False)
				return {
					"media_specification": latest.name,
					"version_number": latest.version_number,
				}
			if self.status not in ("Review", "Needs Attention", "Completed"):
				frappe.throw(_("Storyboard revision is not available in the current Campaign state."))
			revision = frappe.get_doc(
				{
					"doctype": "Media Specification",
					"media_project": self.name,
					"version_number": (latest.version_number or 0) + 1,
					"status": "Draft",
					"workflow_profile": latest.workflow_profile,
					"generation_workflow_version": latest.generation_workflow_version,
					"prompt_template_version": latest.prompt_template_version,
					"total_duration_seconds": latest.total_duration_seconds,
					"delivery_preset": latest.delivery_preset,
					"delivery_width": latest.delivery_width,
					"delivery_height": latest.delivery_height,
					"generation_instructions": latest.generation_instructions,
				}
			).insert(ignore_permissions=True)

		frappe.db.set_value("Media Project", self.name, "status", "Draft", update_modified=False)
		frappe.db.commit()
		return {"media_specification": revision.name, "version_number": revision.version_number}

	@frappe.whitelist()
	def get_pending_reviews(self):
		media_specification = get_latest_media_specification(self.name)
		if not media_specification:
			return []

		shots = frappe.get_all(
			"Shot Specification",
			filters={"media_specification": media_specification.name},
			pluck="name",
		)
		if not shots:
			return []

		jobs = frappe.get_all(
			"Generation Job", filters={"shot_specification": ["in", shots]}, pluck="name"
		)
		if not jobs:
			return []

		attempts = frappe.get_all(
			"Generation Attempt", filters={"generation_job": ["in", jobs]}, pluck="name"
		)
		if not attempts:
			return []

		artifacts = frappe.get_all(
			"Generation Artifact", filters={"generation_attempt": ["in", attempts]}, pluck="name"
		)
		if not artifacts:
			return []

		reviews = frappe.get_all(
			"Quality Review",
			filters={"generation_artifact": ["in", artifacts], "status": "Pending"},
			fields=["name", "generation_artifact"],
			order_by="creation asc",
		)
		return [
			{
				"name": review.name,
				"generation_artifact": review.generation_artifact,
				"preview_url": (
					"/api/method/joymedia.services.artifact_service.stream_review_artifact"
					f"?quality_review_name={review.name}"
				),
			}
			for review in reviews
		]

	def _get_project_image_inputs(self):
		from joymedia.services.project_image_manifest import get_project_image_manifest

		return get_project_image_manifest(self.name, include_data_url=True)
