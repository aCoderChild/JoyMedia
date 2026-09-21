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


@frappe.whitelist()
def get_campaign_cards():
	campaigns = frappe.get_list(
		"Media Project",
		fields=["name", "project_name", "product_name", "status", "modified"],
		order_by="modified desc",
		limit_page_length=100,
	)

	for campaign in campaigns:
		media_specification = get_latest_media_specification(campaign.name)
		campaign.update(
			{
				"duration": media_specification.total_duration_seconds
				if media_specification
				else None,
				"delivery_preset": media_specification.delivery_preset
				if media_specification
				else None,
				"shots": frappe.db.count(
					"Shot Specification",
					{"media_specification": media_specification.name},
				)
				if media_specification
				else 0,
			}
		)

	return campaigns


@frappe.whitelist()
def get_campaign_detail(name):
	frappe.has_permission("Media Project", "read", name, throw=True)
	project = frappe.get_doc("Media Project", name)
	media_specification = get_latest_media_specification(project.name)
	assets = _get_campaign_assets(project.name)

	return {
		"name": project.name,
		"project_name": project.project_name,
		"client_organization": project.client_organization,
		"product_name": project.product_name,
		"target_audience": project.target_audience,
		"video_idea": project.video_idea,
		"status": project.status,
		"video_settings": {
			"name": media_specification.name,
			"duration": media_specification.total_duration_seconds,
			"delivery_preset": media_specification.delivery_preset,
		}
		if media_specification
		else None,
		"assets": assets,
	}


@frappe.whitelist()
def get_campaign_workspace(name):
	frappe.has_permission("Media Project", "read", name, throw=True)
	project = frappe.get_doc("Media Project", name)
	media_specification = get_latest_media_specification(project.name)
	assets = _get_campaign_assets(project.name)
	storyboard = []
	production = None
	reviews = []
	final_video = None

	if media_specification:
		storyboard = frappe.get_all(
			"Shot Specification",
			filters={"media_specification": media_specification.name},
			fields=[
				"name",
				"shot_number",
				"camera_direction",
				"subject_identity",
				"action_plot",
				"environment",
				"audio_direction",
				"planned_frame_count",
				"selected_output_asset_version",
			],
			order_by="shot_number asc, name asc",
		)

		run = frappe.get_all(
			"Generation Run",
			filters={"media_specification": media_specification.name},
			fields=[
				"name",
				"status",
				"progress",
				"completed_jobs",
				"total_jobs",
				"error_summary",
				"final_asset_version",
			],
			order_by="creation desc",
			limit_page_length=1,
		)
		if run:
			production = run[0]
			reviews = project._get_review_cards(["Pending", "Rejected"])
			if production.final_asset_version:
				final_file = frappe.db.get_value(
					"Asset Version", production.final_asset_version, "file"
				)
				final_video = {
					"asset_version": production.final_asset_version,
					"file": final_file,
				}

	return {
		"campaign": {
			"name": project.name,
			"project_name": project.project_name,
			"client_organization": project.client_organization,
			"product_name": project.product_name,
			"target_audience": project.target_audience,
			"video_idea": project.video_idea,
			"status": project.status,
		},
		"assets": assets,
		"video_settings": {
			"name": media_specification.name,
			"version_number": media_specification.version_number,
			"status": media_specification.status,
			"duration": media_specification.total_duration_seconds,
			"delivery_preset": media_specification.delivery_preset,
		}
		if media_specification
		else None,
		"storyboard": storyboard,
		"production": production,
		"reviews": reviews,
		"final_video": final_video,
	}


def _get_campaign_assets(media_project):
	assets = frappe.get_list(
		"Media Asset",
		filters={"media_project": media_project, "status": "Active"},
		fields=["name", "asset_name", "media_type", "asset_category"],
		order_by="modified desc",
		limit_page_length=100,
	)
	for asset in assets:
		versions = frappe.get_all(
			"Asset Version",
			filters={"media_asset": asset.name},
			fields=["file", "version_number"],
			order_by="version_number desc",
			limit_page_length=1,
		)
		asset["file"] = versions[0].file if versions else None
	return assets


@frappe.whitelist()
def get_pending_review_cards():
	reviews = []
	for campaign in frappe.get_list(
		"Media Project",
		fields=["name", "project_name"],
		order_by="modified desc",
		limit_page_length=100,
	):
		project = frappe.get_doc("Media Project", campaign.name)
		for review in project.get_pending_reviews():
			reviews.append(
				{
					"name": review["name"],
					"campaign": campaign.name,
					"campaign_name": campaign.project_name,
					"generation_artifact": review["generation_artifact"],
					"status": review["status"],
					"asset_version": review.get("asset_version"),
					"preview_url": review["preview_url"],
				}
			)
	return reviews


@frappe.whitelist()
def stream_campaign_review(campaign_name: str, review_name: str):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.stream_campaign_review(review_name)


@frappe.whitelist()
def approve_campaign_review(campaign_name: str, review_name: str):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.approve_campaign_review(review_name)


@frappe.whitelist()
def reject_campaign_review(
	campaign_name: str, review_name: str, notes: str | None = None
):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.reject_campaign_review(review_name, notes)


@frappe.whitelist()
def regenerate_campaign_review(
	campaign_name: str,
	review_name: str,
	reason: str = "Human Review Rejection",
):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.regenerate_campaign_review(review_name, reason)


@frappe.whitelist()
def save_campaign_video_settings(campaign_name, total_duration_seconds, delivery_preset):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.save_video_settings(total_duration_seconds, delivery_preset)


@frappe.whitelist()
def generate_campaign_video_plan(campaign_name, scene_count):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.generate_video_plan(scene_count)


@frappe.whitelist()
def apply_campaign_video_plan(campaign_name, plan_json):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.apply_video_plan(plan_json)


@frappe.whitelist()
def generate_campaign_video(campaign_name):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.generate_video()


@frappe.whitelist()
def revise_campaign_storyboard(campaign_name):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.create_storyboard_revision()


@frappe.whitelist()
def get_businesses():
	return frappe.get_list(
		"Client Organization",
		fields=["name", "organization_name", "industry"],
		order_by="organization_name asc",
		limit_page_length=100,
	)


@frappe.whitelist()
def create_business(organization_name, industry=None):
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be signed in to create a business."))
	organization_name = (organization_name or "").strip()
	if not organization_name:
		frappe.throw(_("Business name is required."))

	organization = frappe.get_doc(
		{
			"doctype": "Client Organization",
			"organization_name": organization_name,
			"industry": (industry or "").strip(),
		}
	).insert(ignore_permissions=True)

	user = frappe.get_doc("User", frappe.session.user)
	if not any(role.role == "JoyMedia User" for role in user.roles):
		user.append("roles", {"role": "JoyMedia User"})
		user.save(ignore_permissions=True)

	if not frappe.db.exists(
		"User Permission",
		{"user": frappe.session.user, "allow": "Client Organization", "for_value": organization.name},
	):
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": frappe.session.user,
				"allow": "Client Organization",
				"for_value": organization.name,
				"is_default": 1,
			}
		).insert(ignore_permissions=True)
	frappe.db.commit()
	return organization


@frappe.whitelist()
def create_campaign(
	project_name,
	client_organization,
	product_name,
	target_audience,
	video_idea=None,
):
	frappe.has_permission("Client Organization", "read", client_organization, throw=True)
	if not set(frappe.get_roles()).intersection(
		{"JoyMedia User", "JoyMedia Specialist", "System Manager"}
	):
		frappe.throw(_("You do not have permission to create a Campaign."))
	project = frappe.get_doc(
		{
			"doctype": "Media Project",
			"project_name": project_name,
			"client_organization": client_organization,
			"product_name": product_name,
			"target_audience": target_audience,
			"video_idea": video_idea,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return project


@frappe.whitelist()
def create_campaign_asset(media_project, asset_name, asset_category, file_url):
	frappe.has_permission("Media Project", "write", media_project, throw=True)
	media_project = frappe.get_doc("Media Project", media_project)
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	if file_doc.owner != frappe.session.user and frappe.session.user != "Administrator":
		frappe.throw(_("You can only attach files uploaded by your account."))

	asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": asset_name,
			"asset_scope": "Project",
			"media_type": "Image",
			"asset_category": asset_category,
			"media_project": media_project.name,
			"client_organization": media_project.client_organization,
		}
	).insert(ignore_permissions=True)
	version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": asset.name,
			"file": file_url,
			"source": "Uploaded",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"asset": asset, "version": version}


class MediaProject(Document):
	def _require_read_access(self):
		self.check_permission("read")

	def _require_write_access(self):
		self.check_permission("write")

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
		self._require_read_access()
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
		self._require_write_access()
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
		self._require_read_access()
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
		self._require_write_access()
		from joymedia.services.generation_orchestrator import start_run_internal

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

			result = start_run_internal(run.name)
			frappe.db.commit()
			return {"run": run.name, "status": result["status"]}

	@frappe.whitelist()
	def apply_video_plan(self, plan_json):
		self._require_write_access()
		from joymedia.services.video_plan_service import apply_video_plan, parse_video_plan

		media_specification = get_latest_media_specification(self.name)
		if not media_specification:
			frappe.throw(_("Create Video Settings before applying a storyboard."))

		plan = parse_video_plan(plan_json)
		created_shots = apply_video_plan(
			media_specification_name=media_specification.name,
			plan=plan,
		)
		frappe.db.commit()
		return {
			"media_specification": media_specification.name,
			"shots": created_shots,
		}

	@frappe.whitelist()
	def create_storyboard_revision(self):
		self._require_write_access()
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
		self._require_read_access()
		return self._get_review_cards(["Pending"])

	def _get_review_cards(self, statuses):
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
			filters={"generation_artifact": ["in", artifacts], "status": ["in", statuses]},
			fields=["name", "generation_artifact", "status", "asset_version"],
			order_by="creation asc",
		)
		return [
			{
				"name": review.name,
				"generation_artifact": review.generation_artifact,
				"status": review.status,
				"asset_version": review.asset_version,
				"preview_url": (
					"/api/method/joymedia.joymedia.doctype.media_project.media_project."
					f"stream_campaign_review?campaign_name={self.name}&review_name={review.name}"
				),
			}
			for review in reviews
		]

	def _resolve_campaign_review(self, review_name):
		review = frappe.get_doc("Quality Review", review_name)
		artifact = frappe.get_doc("Generation Artifact", review.generation_artifact)
		attempt = frappe.get_doc("Generation Attempt", artifact.generation_attempt)
		job = frappe.get_doc("Generation Job", attempt.generation_job)
		shot = frappe.get_doc("Shot Specification", job.shot_specification)
		media_specification = frappe.get_doc("Media Specification", shot.media_specification)
		latest = get_latest_media_specification(self.name)
		if media_specification.media_project != self.name or not latest or latest.name != media_specification.name:
			frappe.throw(_("This review does not belong to the current Campaign revision."))
		return review

	@frappe.whitelist()
	def stream_campaign_review(self, review_name):
		self._require_read_access()
		review = self._resolve_campaign_review(review_name)
		from joymedia.services.artifact_service import stream_review_artifact_internal

		return stream_review_artifact_internal(review.name)

	@frappe.whitelist()
	def approve_campaign_review(self, review_name):
		self._require_write_access()
		review = self._resolve_campaign_review(review_name)
		from joymedia.joymedia.doctype.quality_review.quality_review import approve_review_internal

		result = approve_review_internal(review.name)
		frappe.db.commit()
		return result

	@frappe.whitelist()
	def reject_campaign_review(self, review_name, notes=None):
		self._require_write_access()
		review = self._resolve_campaign_review(review_name)
		from joymedia.joymedia.doctype.quality_review.quality_review import reject_review_internal

		result = reject_review_internal(review.name, notes)
		frappe.db.commit()
		return result

	@frappe.whitelist()
	def regenerate_campaign_review(self, review_name, reason="Human Review Rejection"):
		self._require_write_access()
		review = self._resolve_campaign_review(review_name)
		from joymedia.joymedia.doctype.quality_review.quality_review import regenerate_shot_internal

		result = regenerate_shot_internal(review.name, reason)
		frappe.db.commit()
		return result

	def _get_project_image_inputs(self):
		from joymedia.services.project_image_manifest import get_project_image_manifest

		return get_project_image_manifest(self.name, include_data_url=True)
