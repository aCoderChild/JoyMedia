# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.synchronization import filelock

from joymedia.joymedia.doctype.workflow.workflow import get_latest_valid_workflow


ALLOWED_STATUSES = {
	"Draft",
	"Generating",
	"Review",
	"Completed",
	"Needs Attention",
	"Cancelled",
}
MIN_SHOT_DURATION_SECONDS = 2.5
INPUT_ASSET_CATEGORIES = {"Product", "Character", "Background", "Brand", "Style", "Reference"}
OUTPUT_ASSET_CATEGORIES = {"Shot Output", "Final Deliverable", "Storyboard", "Other"}
SHOT_REFERENCE_CATEGORIES = INPUT_ASSET_CATEGORIES


def _normalize_generation_mode(value):
	return {"Independent": "Multi-shot", "Chained": "Continuous", "Consistency": "Continuous"}.get(
		value, value or "Multi-shot"
	)


def _get_customer_workflow(video_style=None):
	workflow = get_latest_valid_workflow(video_style)
	if not workflow and not video_style:
		workflow = get_latest_valid_workflow()
	if not workflow:
		frappe.throw(
			_("Select an active video style configured by JoyMedia.")
			if video_style
			else _("No default MiniMax H3 Workflow is configured.")
		)
	return workflow


def _customer_style_details(media_specification):
	if not media_specification:
		return {}
	workflow = (
		frappe.db.get_value("Workflow", media_specification.workflow, ["workflow_key"], as_dict=True)
		if media_specification.workflow else None
	)
	workflow_name = (
		" ".join(part.capitalize() for part in workflow.workflow_key.split("_"))
		if workflow else None
	)
	return {
		"video_style": media_specification.video_style
			or (workflow.workflow_key if workflow else None),
		"video_style_name": workflow_name,
		"video_style_description": "",
	}


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
		"Campaign",
		fields=["name", "campaign_name", "product_name", "client_organization", "target_audience", "campaign_brief", "modified"],
		order_by="modified desc",
		limit_page_length=100,
	)

	for cam in campaigns:
		campaign_name = cam.name
		projects = frappe.get_all(
			"Media Project",
			filters={"campaign": campaign_name},
			fields=["name", "status"],
			order_by="creation asc, name asc",
		)
		assets = frappe.get_all(
			"Media Asset",
			filters={
				"campaign": campaign_name,
				"asset_scope": "Campaign",
				"status": "Active",
				"asset_category": ["in", list(INPUT_ASSET_CATEGORIES)],
			},
			fields=["name", "asset_category"],
		)
		cover_image = None
		for a in assets:
			v = frappe.db.get_value("Asset Version", {"media_asset": a.name}, "file", order_by="version_number desc")
			if v:
				cover_image = v
				break

		cam.update(
			{
				# Campaign workspace routes currently resolve a Media Project. Keep
				# the parent campaign identity separately for data aggregation.
				"campaign": campaign_name,
				"name": projects[0].name if projects else campaign_name,
				"project_count": len(projects),
				"asset_count": len(assets),
				"cover_image": cover_image,
				"asset_categories": list({a.asset_category for a in assets if a.asset_category}),
				"status": "Active" if projects else "Draft",
			}
		)

	return campaigns


@frappe.whitelist()
def get_video_styles():
	styles = []
	for row in frappe.get_all("Workflow", fields=["workflow_key"], distinct=True):
		workflow = get_latest_valid_workflow(row.workflow_key)
		if workflow:
			label = " ".join(part.capitalize() for part in workflow.workflow_key.split("_"))
			styles.append(frappe._dict(workflow_key=workflow.workflow_key, client_name=label, client_description=""))
	return sorted(styles, key=lambda style: style.client_name)


@frappe.whitelist()
def get_campaign_detail(name):
	if frappe.db.exists("Campaign", name):
		frappe.has_permission("Campaign", "read", name, throw=True)
		campaign = frappe.get_doc("Campaign", name)
	elif frappe.db.exists("Media Project", name):
		project = frappe.get_doc("Media Project", name)
		if project.campaign:
			campaign = frappe.get_doc("Campaign", project.campaign)
		else:
			frappe.throw(_("Project {0} has no parent Campaign").format(name))
	else:
		frappe.throw(_("Campaign {0} not found").format(name))

	# 1. Fetch Shared Assets belonging to this Campaign (input categories only)
	assets = frappe.get_list(
		"Media Asset",
		filters={
			"status": "Active",
			"campaign": campaign.name,
			"asset_scope": "Campaign",
			"asset_category": ["in", list(INPUT_ASSET_CATEGORIES)],
		},
		fields=["name", "asset_name", "media_type", "asset_category", "creation", "modified"],
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

	# 2. Fetch Projects under this Campaign
	projects_raw = frappe.get_list(
		"Media Project",
		filters={"campaign": campaign.name},
		fields=["name", "project_name", "product_name", "video_idea", "status", "modified"],
		order_by="creation desc",
		limit_page_length=50,
	)
	projects = []
	for p in projects_raw:
		media_spec = get_latest_media_specification(p.name)
		shot_count = (
			frappe.db.count("Shot Specification", {"media_specification": media_spec.name})
			if media_spec
			else 0
		)
		final_video_url = None
		run = frappe.get_all(
			"Generation Run",
			filters={"media_specification": media_spec.name} if media_spec else {},
			fields=["final_asset_version"],
			order_by="creation desc",
			limit_page_length=1,
		) if media_spec else []
		if run and run[0].final_asset_version:
			final_video_url = frappe.db.get_value("Asset Version", run[0].final_asset_version, "file")

		projects.append({
			"name": p.name,
			"project_name": p.project_name,
			"video_idea": p.video_idea,
			"status": p.status,
			"duration": media_spec.total_duration_seconds if media_spec else 30,
			"delivery_preset": media_spec.delivery_preset if media_spec else "Landscape",
			"video_style_name": _customer_style_details(media_spec).get("video_style_name") if media_spec else "Showcase",
			"shot_count": shot_count,
			"final_video_url": final_video_url,
		})

	return {
		"campaign": {
			"name": campaign.name,
			"campaign_name": campaign.campaign_name,
			"client_organization": campaign.client_organization,
			"product_name": campaign.product_name,
			"target_audience": campaign.target_audience,
			"campaign_brief": campaign.campaign_brief,
		},
		"shared_assets": assets,
		"projects": projects,
	}


@frappe.whitelist()
def get_campaign_workspace(name):
	frappe.has_permission("Media Project", "read", name, throw=True)
	project = frappe.get_doc("Media Project", name)
	media_specification = get_latest_media_specification(project.name)
	assets = _get_campaign_assets(project.name)
	outputs = _get_project_outputs(project.name)
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
				"generation_prompt",
				"planned_frame_count",
				"selected_output_asset_version",
			],
			order_by="shot_number asc, name asc",
		)
		for shot in storyboard:
			input_rows = frappe.get_all(
				"Shot Input Mapping",
				filters={"parent": shot["name"]},
				fields=["input_role", "asset_version"],
				limit_page_length=20,
			)
			first_frame = next(
				(
					row
					for row in input_rows
					if frappe.scrub(row.input_role or "") in ("first_frame", "reference_image", "image")
				),
				None,
			)
			if first_frame:
				asset_version = frappe.db.get_value(
					"Asset Version",
					first_frame.asset_version,
					["file", "media_asset"],
					as_dict=True,
				)
				if asset_version:
					shot["reference_image"] = asset_version.file
					shot["reference_asset_name"] = frappe.db.get_value(
						"Media Asset", asset_version.media_asset, "asset_name"
					)

			last_frame = next(
				(
					row
					for row in input_rows
					if frappe.scrub(row.input_role or "") == "last_frame"
				),
				None,
			)
			if last_frame:
				asset_version = frappe.db.get_value(
					"Asset Version",
					last_frame.asset_version,
					["file", "media_asset"],
					as_dict=True,
				)
				if asset_version:
					shot["last_frame_image"] = asset_version.file
					shot["last_frame_asset_name"] = frappe.db.get_value(
						"Media Asset", asset_version.media_asset, "asset_name"
					)

		run = frappe.get_all(
			"Generation Run",
			filters={"media_specification": media_specification.name},
			fields=[
				"name",
				"status",
				"queued_at",
				"started_at",
				"completed_at",
				"progress",
				"completed_jobs",
				"total_jobs",
				"failed_jobs",
				"error_summary",
		"final_asset_version",
			],
			order_by="creation desc",
			limit_page_length=1,
		)
		if run:
			production = run[0]
			reviews = project._get_review_cards(["Pending", "Rejected", "Approved"])
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
		"project": {
			"name": project.name,
			"project_name": project.project_name,
			"video_idea": project.video_idea,
			"reference_template": project.reference_template,
			"status": project.status,
		},
		"campaign_parent": frappe.db.get_value(
			"Campaign",
			project.campaign,
			["name", "campaign_name", "client_organization", "product_name", "target_audience", "campaign_brief"],
			as_dict=True,
		)
		if project.campaign
		else None,
		"assets": assets,
		"outputs": outputs,
		"video_settings": {
			"name": media_specification.name,
			"version_number": media_specification.version_number,
			"status": media_specification.status,
			"duration": media_specification.total_duration_seconds,
			"delivery_preset": media_specification.delivery_preset,
			"continuity_mode": _normalize_generation_mode(
				getattr(media_specification, "continuity_mode", None)
			),
			"automatic_shot_count": _automatic_shot_count(media_specification, project.name),
			"reference_asset_count": _reference_asset_count(project.name),
			**_customer_style_details(media_specification),
		}
		if media_specification
		else None,
		"storyboard": storyboard,
		"production": production,
		"reviews": reviews,
		"final_video": final_video,
	}


@frappe.whitelist()
def get_project_workspace(name):
	return get_campaign_workspace(name)
@frappe.whitelist()
def get_campaign_production(name):
	"""Return only the current Campaign production state for lightweight polling."""
	frappe.has_permission("Media Project", "read", name, throw=True)
	project = frappe.get_doc("Media Project", name)
	media_specification = get_latest_media_specification(project.name)
	if not media_specification:
		return None

	run = frappe.get_all(
		"Generation Run",
		filters={"media_specification": media_specification.name},
		fields=[
			"name",
			"status",
			"queued_at",
			"started_at",
			"completed_at",
			"progress",
			"completed_jobs",
			"total_jobs",
			"failed_jobs",
			"running_jobs",
			"error_summary",
			"final_asset_version",
		],
		order_by="creation desc",
		limit_page_length=1,
	)
	if not run:
		return None
	production = run[0]
	if production.final_asset_version:
		production["final_video"] = {
			"asset_version": production.final_asset_version,
			"file": frappe.db.get_value("Asset Version", production.final_asset_version, "file"),
		}
	return production


@frappe.whitelist()
def get_campaign_reviews(name):
	"""Return review cards only, so the workspace can refresh review state cheaply."""
	frappe.has_permission("Media Project", "read", name, throw=True)
	project = frappe.get_doc("Media Project", name)
	return project._get_review_cards(["Pending", "Rejected", "Approved"])

def _get_campaign_assets(media_project):
	"""Return only visual references explicitly selected for this project."""
	assets = frappe.get_list(
		"Media Asset",
		filters={
			"status": "Active",
			"media_project": media_project,
			"asset_scope": "Project",
			"asset_category": ["in", list(INPUT_ASSET_CATEGORIES)],
		},
		fields=["name", "asset_name", "media_type", "asset_category", "asset_scope"],
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
def get_project_reference_candidates(media_project):
	project = frappe.get_doc("Media Project", media_project)
	project._require_read_access()
	if not project.campaign:
		return []

	campaign_assets = frappe.get_list(
		"Media Asset",
		filters={
			"campaign": project.campaign,
			"asset_scope": "Campaign",
			"status": "Active",
			"media_type": "Image",
			"asset_category": ["in", list(INPUT_ASSET_CATEGORIES)],
		},
		fields=["name", "asset_name", "asset_category"],
		order_by="modified desc",
		limit_page_length=100,
	)
	selected_files = set()
	for selected in frappe.get_all(
		"Media Asset",
		filters={"media_project": project.name, "asset_scope": "Project", "status": "Active"},
		pluck="name",
	):
		file_url = frappe.db.get_value(
			"Asset Version", {"media_asset": selected}, "file", order_by="version_number desc"
		)
		if file_url:
			selected_files.add(file_url)

	for asset in campaign_assets:
		asset["file"] = frappe.db.get_value(
			"Asset Version", {"media_asset": asset.name}, "file", order_by="version_number desc"
		)
		asset["selected"] = bool(asset.file and asset.file in selected_files)
	return campaign_assets


@frappe.whitelist()
def select_project_reference(media_project, asset_name):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	if not project.campaign:
		frappe.throw(_("This project is not attached to a Campaign."))

	source = frappe.get_doc("Media Asset", asset_name)
	if (
		source.asset_scope != "Campaign"
		or source.campaign != project.campaign
		or source.status != "Active"
		or source.media_type != "Image"
		or source.asset_category not in INPUT_ASSET_CATEGORIES
	):
		frappe.throw(_("That asset is not available as a reference for this project."))

	file_url = frappe.db.get_value(
		"Asset Version", {"media_asset": source.name}, "file", order_by="version_number desc"
	)
	if not file_url:
		frappe.throw(_("The selected asset has no file version."))

	for selected in frappe.get_all(
		"Media Asset",
		filters={"media_project": project.name, "asset_scope": "Project", "status": "Active"},
		pluck="name",
	):
		if frappe.db.get_value(
			"Asset Version", {"media_asset": selected}, "file", order_by="version_number desc"
		) == file_url:
			return {"name": selected, "selected": True}

	selected = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": source.asset_name,
			"asset_scope": "Project",
			"media_project": project.name,
			"media_type": "Image",
			"asset_category": source.asset_category,
			"status": "Active",
			"client_organization": project.client_organization,
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": selected.name,
			"version_number": 1,
			"file": file_url,
			"source": "Imported",
			"derived_from": frappe.db.get_value(
				"Asset Version", {"media_asset": source.name}, "name", order_by="version_number desc"
			),
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": selected.name, "selected": True}


def _get_project_outputs(media_project):
	"""Return only machine-generated project outputs (scene clips, master videos, frames)."""
	assets = frappe.get_list(
		"Media Asset",
		filters={
			"status": "Active",
			"media_project": media_project,
			"asset_category": ["in", list(OUTPUT_ASSET_CATEGORIES)],
		},
		fields=["name", "asset_name", "media_type", "asset_category", "asset_scope", "modified"],
		order_by="creation desc",
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


def _minimum_shot_count(media_specification):
	if not media_specification or not media_specification.workflow:
		return 1

	workflow_version = frappe.get_doc(
		"Workflow", media_specification.workflow
	)
	frame_count = int(workflow_version.frame_count or 0)
	output_fps = float(workflow_version.output_fps or 0)
	if frame_count < 1 or output_fps <= 0:
		return 1

	return max(
		1,
		math.ceil(
			float(media_specification.total_duration_seconds or 0)
			* output_fps
			/ frame_count
		),
	)


def _reference_asset_count(media_project):
	from joymedia.services.project_image_manifest import get_project_image_manifest

	return sum(
		item.get("asset_category") in SHOT_REFERENCE_CATEGORIES
		for item in get_project_image_manifest(media_project)
	)


def _automatic_shot_count(media_specification, media_project):
	technical_minimum = _minimum_shot_count(media_specification)
	if not media_specification:
		return technical_minimum

	duration = float(media_specification.total_duration_seconds or 0)
	max_creative_shots = max(
		technical_minimum,
		math.floor(duration / MIN_SHOT_DURATION_SECONDS),
	)
	return min(
		max(technical_minimum, _reference_asset_count(media_project)),
		max_creative_shots,
	)


@frappe.whitelist()
def get_pending_review_cards():
	"""
	Return only full videos ready for final client review:
	- Merged/composed multi-shot final deliverable videos
	- Single-shot campaign full videos
	Individual intermediate scene shots are reviewed within CampaignDetail.vue.
	"""
	full_videos = []
	for campaign in frappe.get_list(
		"Media Project",
		fields=["name", "project_name", "product_name", "status"],
		order_by="modified desc",
		limit_page_length=100,
	):
		project = frappe.get_doc("Media Project", campaign.name)
		media_spec = get_latest_media_specification(project.name)
		if not media_spec:
			continue

		shots = frappe.get_all(
			"Shot Specification",
			filters={"media_specification": media_spec.name},
			pluck="name",
		)
		shot_count = len(shots)
		if shot_count == 0:
			continue

		# Case 1: Multi-shot campaign -> Only show the composed / merged full video
		if shot_count > 1:
			final_asset = None
			if media_spec.final_asset_version:
				asset_ver = frappe.get_doc("Asset Version", media_spec.final_asset_version)
				if asset_ver.file:
					final_asset = {
						"file": asset_ver.file,
						"version": asset_ver.name,
						"duration": asset_ver.duration_seconds or media_spec.total_duration_seconds,
					}
			if not final_asset:
				deliv_asset_name = frappe.db.get_value(
					"Media Asset",
					{"media_project": project.name, "asset_category": "Final Deliverable"},
					"name",
				)
				if deliv_asset_name:
					latest_v = frappe.get_all(
						"Asset Version",
						filters={"media_asset": deliv_asset_name},
						fields=["name", "file", "duration_seconds"],
						order_by="creation desc",
						limit=1,
					)
					if latest_v and latest_v[0].file:
						final_asset = {
							"file": latest_v[0].file,
							"version": latest_v[0].name,
							"duration": latest_v[0].duration_seconds or media_spec.total_duration_seconds,
						}
			if final_asset:
				full_videos.append(
					{
						"name": f"{project.name}-FULL",
						"campaign": project.name,
						"campaign_name": project.project_name,
						"product_name": project.product_name,
						"video_type": "Merged Full Video",
						"shot_count": shot_count,
						"status": "Ready for Review" if project.status in ("Review", "Completed") else project.status,
						"preview_url": final_asset["file"],
						"duration": final_asset.get("duration"),
						"asset_version": final_asset.get("version"),
						"is_single_shot": False,
					}
				)

		# Case 2: Single-shot campaign -> The single shot video IS the full video!
		elif shot_count == 1:
			reviews = project.get_pending_reviews()
			if reviews:
				review = reviews[0]
				full_videos.append(
					{
						"name": review["name"],
						"campaign": project.name,
						"campaign_name": project.project_name,
						"product_name": project.product_name,
						"video_type": "Single-Shot Full Video",
						"shot_count": 1,
						"status": review["status"],
						"preview_url": review["preview_url"],
						"asset_version": review.get("asset_version"),
						"is_single_shot": True,
					}
				)
			elif media_spec.final_asset_version:
				asset_ver = frappe.get_doc("Asset Version", media_spec.final_asset_version)
				if asset_ver.file:
					full_videos.append(
						{
							"name": f"{project.name}-FULL",
							"campaign": project.name,
							"campaign_name": project.project_name,
							"product_name": project.product_name,
							"video_type": "Single-Shot Full Video",
							"shot_count": 1,
							"status": "Ready for Review" if project.status in ("Review", "Completed") else project.status,
							"preview_url": asset_ver.file,
							"duration": asset_ver.duration_seconds or media_spec.total_duration_seconds,
							"asset_version": asset_ver.name,
							"is_single_shot": True,
						}
					)

	# Also include any Quality Review records in the system
	qr_records = frappe.get_all(
		"Quality Review",
		fields=["name", "status", "asset_version", "generation_artifact", "notes", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)
	seen_ids = {v["name"] for v in full_videos}
	for qr in qr_records:
		if qr.name in seen_ids:
			continue
		preview_url = None
		if qr.asset_version:
			preview_url = frappe.db.get_value("Asset Version", qr.asset_version, "file")
		if not preview_url and qr.generation_artifact:
			preview_url = frappe.db.get_value("Generation Artifact", qr.generation_artifact, "frappe_file")
		if not preview_url:
			preview_url = f"/api/method/joymedia.services.artifact_service.stream_review_artifact?quality_review_name={qr.name}"

		proj_name = None
		prod_name = None
		if qr.generation_artifact:
			att = frappe.db.get_value("Generation Artifact", qr.generation_artifact, "generation_attempt")
			if att:
				job = frappe.db.get_value("Generation Attempt", att, "generation_job")
				if job:
					shot = frappe.db.get_value("Generation Job", job, "shot_specification")
					if shot:
						spec = frappe.db.get_value("Shot Specification", shot, "media_specification")
						if spec:
							proj_name = frappe.db.get_value("Media Specification", spec, "media_project")
							if proj_name:
								prod_name = frappe.db.get_value("Media Project", proj_name, "product_name")

		full_videos.append({
			"name": qr.name,
			"review_name": qr.name,
			"campaign": proj_name or "Project",
			"campaign_name": proj_name or qr.name,
			"product_name": prod_name or "Generated Video Clip",
			"video_type": "Generated Video Clip",
			"shot_count": 1,
			"status": qr.status or "Pending",
			"preview_url": preview_url,
			"asset_version": qr.asset_version,
			"generation_artifact": qr.generation_artifact,
			"notes": qr.notes,
			"is_single_shot": True,
		})

	return full_videos


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
def approve_review(review_name: str, campaign_name: str | None = None):
	if campaign_name and frappe.db.exists("Media Project", campaign_name):
		return approve_campaign_review(campaign_name, review_name)
	review = frappe.get_doc("Quality Review", review_name)
	review.check_permission("write")
	review.status = "Approved"
	review.save(ignore_permissions=True)
	frappe.db.commit()
	return review.as_dict()


@frappe.whitelist()
def reject_review(review_name: str, campaign_name: str | None = None, notes: str | None = None):
	if campaign_name and frappe.db.exists("Media Project", campaign_name):
		return reject_campaign_review(campaign_name, review_name, notes)
	review = frappe.get_doc("Quality Review", review_name)
	review.check_permission("write")
	review.status = "Rejected"
	if notes:
		review.notes = notes
	review.save(ignore_permissions=True)
	frappe.db.commit()
	return review.as_dict()


@frappe.whitelist()
def regenerate_campaign_review(
	campaign_name: str,
	review_name: str,
	reason: str = "Human Review Rejection",
):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.regenerate_campaign_review(review_name, reason)


@frappe.whitelist()
def save_campaign_video_settings(
	campaign_name, total_duration_seconds, delivery_preset, video_style=None, continuity_mode=None
):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.save_video_settings(
		total_duration_seconds, delivery_preset, video_style, continuity_mode
	)


@frappe.whitelist()
def generate_campaign_video_plan(campaign_name):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.generate_video_plan()


@frappe.whitelist()
def apply_campaign_video_plan(campaign_name, plan_json):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.apply_video_plan(plan_json)


@frappe.whitelist()
def generate_campaign_video(campaign_name):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.generate_video()


@frappe.whitelist()
def retry_campaign_failed_jobs(campaign_name):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.retry_failed_jobs()


@frappe.whitelist()
def revise_campaign_storyboard(campaign_name, use_current_workflow_defaults=False):
	campaign = frappe.get_doc("Media Project", campaign_name)
	return campaign.create_storyboard_revision(use_current_workflow_defaults)


@frappe.whitelist()
def update_campaign_shot(campaign_name, shot_name, values):
	campaign = frappe.get_doc("Media Project", campaign_name)
	campaign._require_write_access()
	shot = frappe.get_doc("Shot Specification", shot_name)
	media_specification = get_latest_media_specification(campaign.name)
	if not media_specification or shot.media_specification != media_specification.name:
		frappe.throw(_("Shot does not belong to the current Campaign revision."))
	if media_specification.status != "Draft":
		frappe.throw(
			_(
				"This storyboard revision has already been submitted for generation and cannot be edited. "
				"Create another version to make changes."
			)
		)

	if isinstance(values, str):
		values = frappe.parse_json(values)

	updatable_fields = [
		"subject_identity",
		"action_plot",
		"camera_direction",
		"environment",
		"audio_direction",
	]
	for f in updatable_fields:
		if f in values:
			setattr(shot, f, values[f])

	# The generation prompt is derived from the editable storyboard fields. Do
	# not trust a prompt snapshot sent by the browser: it may be stale after a
	# continuous-mode shot is edited.
	from joymedia.services.prompt_compiler import compile_prompt_for_documents

	shot.generation_prompt = ""
	shot.generation_prompt = compile_prompt_for_documents(shot, media_specification)
	shot.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"name": shot.name,
		"shot_number": shot.shot_number,
		"camera_direction": shot.camera_direction,
		"subject_identity": shot.subject_identity,
		"action_plot": shot.action_plot,
		"environment": shot.environment,
		"audio_direction": shot.audio_direction,
		"generation_prompt": shot.generation_prompt,
	}


@frappe.whitelist()
def regenerate_campaign_shot(campaign_name, shot_name):
	campaign = frappe.get_doc("Media Project", campaign_name)
	campaign._require_write_access()
	shot = frappe.get_doc("Shot Specification", shot_name)

	reviews = frappe.get_all(
		"Quality Review",
		filters={"shot_specification": shot.name},
		fields=["name", "status"],
		order_by="creation desc",
		limit_page_length=1,
	)
	if reviews:
		review = reviews[0]
		if review.status != "Rejected":
			from joymedia.joymedia.doctype.quality_review.quality_review import reject_review_internal
			reject_review_internal(review.name, notes="Regenerated from Storyboard")
		from joymedia.joymedia.doctype.quality_review.quality_review import regenerate_shot_internal
		return regenerate_shot_internal(review.name, reason="Human Review Rejection")

	job_name = frappe.db.get_value(
		"Generation Job",
		{"shot_specification": shot.name},
		"name",
		order_by="creation desc",
	)
	if job_name:
		job = frappe.get_doc("Generation Job", job_name)
		if job.status in ("Failed", "Partially Completed"):
			from joymedia.services.generation_orchestrator import _retry_and_submit_latest_failed_attempts
			results = _retry_and_submit_latest_failed_attempts(job, "Human Review Rejection")
			frappe.db.commit()
			return {"generation_job": job.name, "attempts": results}

	frappe.throw(_("Cannot regenerate shot before generating the video."))


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

	# A previous organization cleanup can leave User Permission rows pointing to
	# deleted Client Organization records. Remove those stale rows and clear any
	# existing default before assigning the newly created business as default.
	for permission in frappe.get_all(
		"User Permission",
		filters={"user": frappe.session.user, "allow": "Client Organization"},
		fields=["name", "for_value"],
	):
		if not frappe.db.exists("Client Organization", permission.for_value):
			frappe.delete_doc("User Permission", permission.name, ignore_permissions=True, force=True)
		else:
			frappe.db.set_value("User Permission", permission.name, "is_default", 0, update_modified=False)

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
	campaign_name=None,
):
	frappe.has_permission("Client Organization", "read", client_organization, throw=True)
	if not set(frappe.get_roles()).intersection(
		{"JoyMedia User", "JoyMedia Specialist", "System Manager"}
	):
		frappe.throw(_("You do not have permission to create a Campaign."))
	campaign = frappe.get_doc(
		{
			"doctype": "Campaign",
			"campaign_name": campaign_name or project_name,
			"client_organization": client_organization,
			"product_name": product_name,
			"target_audience": target_audience,
			"campaign_brief": video_idea,
		}
	).insert(ignore_permissions=True)
	project = frappe.get_doc(
		{
			"doctype": "Media Project",
			"campaign": campaign.name,
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
def create_campaign_project(
	campaign,
	project_name,
	video_idea=None,
	duration=30,
	format="Landscape",
	video_style=None,
):
	frappe.has_permission("Campaign", "write", campaign, throw=True)
	campaign_doc = frappe.get_doc("Campaign", campaign)

	project = frappe.get_doc(
		{
			"doctype": "Media Project",
			"campaign": campaign_doc.name,
			"project_name": (project_name or "").strip(),
			"client_organization": campaign_doc.client_organization,
			"product_name": campaign_doc.product_name,
			"target_audience": campaign_doc.target_audience,
			"video_idea": (video_idea or "").strip(),
			"status": "Draft",
		}
	).insert(ignore_permissions=True)

	workflow = _get_customer_workflow(video_style)
	frappe.get_doc(
		{
			"doctype": "Media Specification",
			"media_project": project.name,
			"version_number": 1,
			"status": "Draft",
			"workflow": workflow.name,
			"video_style": workflow.workflow_key,
			"total_duration_seconds": float(duration or 30),
			"delivery_preset": format or "Landscape",
		}
	).insert(ignore_permissions=True)

	frappe.db.commit()
	return {"project": project.name, "campaign": campaign_doc.name}


@frappe.whitelist()
def create_campaign_shared_asset(campaign, asset_name, asset_category, file_url):
	frappe.has_permission("Campaign", "write", campaign, throw=True)
	campaign_doc = frappe.get_doc("Campaign", campaign)
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	if file_doc.owner != frappe.session.user and frappe.session.user != "Administrator":
		frappe.throw(_("You can only attach files uploaded by your account."))

	if asset_category not in INPUT_ASSET_CATEGORIES:
		frappe.throw(_("Shared Campaign assets must be reference inputs (Product, Character, Background, Brand, Style, Reference)."))

	asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": (asset_name or "").strip(),
			"asset_scope": "Campaign",
			"campaign": campaign_doc.name,
			"media_type": "Image",
			"asset_category": asset_category,
			"client_organization": campaign_doc.client_organization,
			"status": "Active",
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
	return {"asset": asset.name, "version": version.name}


@frappe.whitelist()
def get_library_assets(scope=None, asset_type=None):
	filters = {"status": "Active"}
	if scope and scope != "All":
		filters["asset_scope"] = scope
	if asset_type == "Inputs":
		filters["asset_category"] = ["in", list(INPUT_ASSET_CATEGORIES)]
	elif asset_type == "Outputs":
		filters["asset_category"] = ["in", list(OUTPUT_ASSET_CATEGORIES)]

	assets = frappe.get_list(
		"Media Asset",
		filters=filters,
		fields=["name", "asset_name", "media_type", "asset_category", "asset_scope", "campaign", "media_project", "status", "modified"],
		order_by="modified desc",
		limit_page_length=100,
	)
	for a in assets:
		v = frappe.get_all(
			"Asset Version",
			filters={"media_asset": a.name},
			fields=["file"],
			order_by="version_number desc",
			limit_page_length=1,
		)
		a["file"] = v[0].file if v else None
		a["is_output"] = a.asset_category in OUTPUT_ASSET_CATEGORIES

	return assets


@frappe.whitelist()
def create_project(campaign, project_name, video_idea=None, reference_template=None):
	"""Create a video deliverable under an existing Campaign."""
	frappe.has_permission("Campaign", "read", campaign, throw=True)
	if not set(frappe.get_roles()).intersection(
		{"JoyMedia User", "JoyMedia Specialist", "System Manager"}
	):
		frappe.throw(_("You do not have permission to create a Project."))

	campaign_doc = frappe.get_doc("Campaign", campaign)
	project = frappe.get_doc(
		{
			"doctype": "Media Project",
			"campaign": campaign_doc.name,
			"project_name": project_name,
			"client_organization": campaign_doc.client_organization,
			"product_name": campaign_doc.product_name,
			"target_audience": campaign_doc.target_audience,
			"video_idea": video_idea,
			"reference_template": reference_template,
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

	asset_fields = {
		"doctype": "Media Asset",
		"asset_name": asset_name,
		"asset_scope": "Campaign" if media_project.campaign else "Project",
		"media_type": "Image",
		"asset_category": asset_category,
		"client_organization": media_project.client_organization,
	}
	if media_project.campaign:
		asset_fields["campaign"] = media_project.campaign
	else:
		asset_fields["media_project"] = media_project.name
	asset = frappe.get_doc(
		asset_fields
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
		if self.campaign:
			campaign = frappe.get_doc("Campaign", self.campaign)
			self.client_organization = campaign.client_organization
			self.product_name = campaign.product_name
			self.target_audience = campaign.target_audience

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
			"continuity_mode": _normalize_generation_mode(media_specification.continuity_mode),
			**_customer_style_details(media_specification),
		}

	@frappe.whitelist()
	def save_video_settings(
		self, total_duration_seconds, delivery_preset, video_style=None, continuity_mode=None
	):
		self._require_write_access()
		try:
			total_duration_seconds = float(total_duration_seconds)
		except (TypeError, ValueError):
			frappe.throw(_("Duration must be greater than zero."))

		if total_duration_seconds <= 0:
			frappe.throw(_("Duration must be greater than zero."))
		if delivery_preset not in ("Landscape", "Portrait", "Square"):
			frappe.throw(_("Select Landscape, Portrait, or Square format."))
		if continuity_mode is not None:
			continuity_mode = {
				"Independent": "Multi-shot",
				"Chained": "Continuous",
				"Consistency": "Continuous",
			}.get(continuity_mode, continuity_mode)
			if continuity_mode not in ("Multi-shot", "Continuous"):
				frappe.throw(_("Select Continuous or Multi-shot generation mode."))

		with filelock(f"joymedia-video-settings-{self.name}"):
			latest = get_latest_media_specification(self.name)
			if latest and latest.status != "Draft":
				frappe.throw(
					_(
						"Video Settings cannot be changed after generation starts. "
						"Use Revise Storyboard first."
					)
				)

			if video_style is None and latest:
				video_style = latest.video_style
			if continuity_mode is None and latest:
				continuity_mode = latest.continuity_mode
			continuity_mode = continuity_mode or "Multi-shot"
			workflow = _get_customer_workflow(video_style)

			if latest:
				latest.total_duration_seconds = total_duration_seconds
				latest.delivery_preset = delivery_preset
				latest.workflow = workflow.name
				latest.video_style = workflow.workflow_key
				latest.continuity_mode = continuity_mode
				latest.save(ignore_permissions=True)
				media_specification = latest
			else:
				media_specification = frappe.get_doc(
					{
						"doctype": "Media Specification",
						"media_project": self.name,
						"version_number": 1,
						"status": "Draft",
						"workflow": workflow.name,
						"video_style": workflow.workflow_key,
						"continuity_mode": continuity_mode,
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
			"video_style": workflow.workflow_key,
			"continuity_mode": continuity_mode,
			"video_style_name": " ".join(part.capitalize() for part in workflow.workflow_key.split("_")),
		}

	@frappe.whitelist()
	def generate_video_plan(self):
		self._require_read_access()
		from joymedia.services.qwen_client import generate_video_plan

		media_specification = get_latest_media_specification(self.name)
		if not media_specification:
			frappe.throw(_("Create Video Settings before generating a storyboard."))
		if media_specification.status != "Draft":
			frappe.throw(_("The current Campaign revision is not editable."))
		if not media_specification.workflow:
			frappe.throw(_("Media Specification must have a Workflow."))

		workflow_version = frappe.get_doc(
			"Workflow",
			media_specification.workflow,
		)

		shot_count = _automatic_shot_count(media_specification, self.name)

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
			shot_count=shot_count,
			reference_template=template,
			reference_images=self._get_project_image_inputs(),
			video_style=media_specification.video_style or workflow_version.workflow_key,
			generation_mode=media_specification.continuity_mode,
		)

	@frappe.whitelist()
	def generate_video(self):
		self._require_write_access()
		from joymedia.services.generation_orchestrator import (
			start_run_internal,
			validate_generation_preflight,
		)

		with filelock(f"joymedia-generate-video-{self.name}"):
			media_specification = get_latest_media_specification(self.name)
			if not media_specification:
				frappe.throw(_("This Campaign has no Video Settings."))

			media_specification.reload()
			existing_run = frappe.db.get_value(
				"Generation Run",
				{
					"media_specification": media_specification.name,
					"status": ["not in", ["Completed", "Failed", "Partially Completed", "Cancelled"]],
				},
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
			workflow = frappe.get_doc("Workflow", media_specification.workflow)
			shots = frappe.get_all(
				"Shot Specification",
				filters={"media_specification": media_specification.name},
				fields=["name", "shot_number", "planned_frame_count"],
				order_by="shot_number asc, name asc",
			)
			validate_generation_preflight(
				media_specification,
				workflow,
				shots,
				check_comfyui=True,
			)
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
	def retry_failed_jobs(self):
		self._require_write_access()
		from joymedia.services.generation_orchestrator import retry_failed_jobs_internal

		media_specification = get_latest_media_specification(self.name)
		if not media_specification:
			frappe.throw(_("This Campaign has no Video Settings."))

		run_name = frappe.db.get_value(
			"Generation Run",
			{
				"media_specification": media_specification.name,
				"status": ["in", ["Failed", "Partially Completed"]],
			},
			"name",
			order_by="creation desc",
		)
		if not run_name:
			frappe.throw(_("This Campaign has no failed video run to retry."))

		workflow_version_name = frappe.db.get_value(
			"Generation Run", run_name, "workflow_version"
		)
		workflow_version = frappe.get_doc("Workflow", workflow_version_name)
		from joymedia.services.workflow_resolver import validate_workflow_bindings

		try:
			validate_workflow_bindings(workflow_version)
		except frappe.ValidationError:
			frappe.throw(
				_(
					"Retry is unavailable because the selected Workflow has an "
					"invalid binding. Fix the Workflow before retrying."
				)
			)

		return retry_failed_jobs_internal(run_name)

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
	def create_storyboard_revision(self, use_current_workflow_defaults=False):
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
			latest_run_status = frappe.db.get_value(
				"Generation Run",
				{"media_specification": latest.name},
				"status",
				order_by="creation desc",
			)
			if self.status not in ("Review", "Needs Attention", "Completed") and latest_run_status not in (
				"Failed",
				"Partially Completed",
			):
				frappe.throw(_("Storyboard revision is not available in the current Campaign state."))
			workflow = latest.workflow
			if isinstance(use_current_workflow_defaults, str):
				use_current_workflow_defaults = frappe.parse_json(use_current_workflow_defaults)
			if use_current_workflow_defaults:
				current_workflow = get_latest_valid_workflow(latest.video_style)
				if not current_workflow:
					frappe.throw(_("No default Workflow is configured."))
				workflow = current_workflow.name

			revision = frappe.get_doc(
				{
					"doctype": "Media Specification",
					"media_project": self.name,
					"version_number": (latest.version_number or 0) + 1,
					"status": "Draft",
					"workflow": workflow,
					"video_style": latest.video_style
					or frappe.db.get_value("Workflow", workflow, "workflow_key"),
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
		cards = []
		for review in reviews:
			card = {
				"name": review.name,
				"generation_artifact": review.generation_artifact,
				"status": review.status,
				"asset_version": review.asset_version,
				"preview_url": (
					"/api/method/joymedia.joymedia.doctype.media_project.media_project."
					f"stream_campaign_review?campaign_name={self.name}&review_name={review.name}"
				),
			}
			artifact_attempt = frappe.db.get_value(
				"Generation Artifact", review.generation_artifact, "generation_attempt"
			)
			if artifact_attempt:
				job = frappe.db.get_value(
					"Generation Attempt", artifact_attempt, "generation_job"
				)
				if job:
					shot_spec = frappe.db.get_value(
						"Generation Job", job, "shot_specification"
					)
					if shot_spec:
						shot_data = frappe.db.get_value(
							"Shot Specification",
							shot_spec,
							["name", "shot_number", "camera_direction", "subject_identity"],
							as_dict=True,
						)
						if shot_data:
							card["shot_name"] = shot_data.name
							card["shot_number"] = shot_data.shot_number
							card["camera_direction"] = shot_data.camera_direction
							card["subject_identity"] = shot_data.subject_identity
			cards.append(card)
		return cards

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
