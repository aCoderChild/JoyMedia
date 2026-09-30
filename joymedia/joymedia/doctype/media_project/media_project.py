# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.synchronization import filelock

from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow


ALLOWED_STATUSES = {
	"Draft",
	"Generating",
	"Completed",
	"Needs Attention",
	"Cancelled",
}
MIN_SHOT_DURATION_SECONDS = 2.5
INPUT_ASSET_CATEGORIES = {"Product", "Character", "Background", "Brand", "Style", "Reference"}
SHOT_REFERENCE_CATEGORIES = INPUT_ASSET_CATEGORIES


def _asset_scope_filters():
	return {"status": "Active", "asset_scope": "Library"}


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


def _meaningful_project_value(value, fallback):
	value = (value or "").strip()
	return value if value and value.lower() != "untitled" else fallback


def _customer_style_details(media_specification):
	if not media_specification:
		return {}
	workflow = (
	frappe.db.get_value("Generation Workflow", media_specification.workflow, ["workflow_key"], as_dict=True)
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


def _get_project_specification_names(media_project):
	return frappe.get_all(
		"Media Specification",
		filters={"media_project": media_project},
		pluck="name",
		order_by="version_number desc, creation desc",
	)


def _get_latest_project_storyboard_specification(media_project, specification_names=None):
	specification_names = specification_names or _get_project_specification_names(media_project)
	for specification_name in specification_names:
		if frappe.db.exists("Shot Specification", {"media_specification": specification_name}):
			return frappe.get_doc("Media Specification", specification_name)
	return get_latest_media_specification(media_project)


def _get_latest_project_generation_run(media_project, specification_names=None):
	specification_names = specification_names or _get_project_specification_names(media_project)
	if not specification_names:
		return None
	runs = frappe.get_all(
		"Generation Run",
		filters={"media_specification": ["in", specification_names]},
		fields=[
			"name",
			"media_specification",
			"status",
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
	return runs[0] if runs else None


def _copy_storyboard_shots(source_specification, target_specification):
	"""Copy a storyboard into a draft specification for continued editing."""
	if frappe.db.exists("Shot Specification", {"media_specification": target_specification.name}):
		return

	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": source_specification.name},
		pluck="name",
		order_by="shot_number asc, name asc",
	)
	for shot_name in shots:
		source = frappe.get_doc("Shot Specification", shot_name)
		copy = frappe.get_doc(
			{
				"doctype": "Shot Specification",
				"media_specification": target_specification.name,
				"shot_number": source.shot_number,
				"shot_name": source.shot_name,
				"planned_frame_count": source.planned_frame_count,
				"duration_seconds": source.duration_seconds,
				"generation_prompt": source.generation_prompt,
			}
		)
		for input_row in source.generation_inputs or []:
			copy.append(
				"generation_inputs",
				{
					"input_role": input_row.input_role,
					"asset_version": input_row.asset_version,
				},
			)
		copy.insert(ignore_permissions=True)


@frappe.whitelist()
def get_project_cards():
	filters = {}
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		filters["owner"] = frappe.session.user
	projects = frappe.get_list(
		"Media Project",
		filters=filters,
		fields=["name", "project_name", "product_name", "campaign_brief", "video_idea", "status", "modified"],
		order_by="modified desc",
		limit_page_length=100,
	)

	for project in projects:
		asset_filters = _asset_scope_filters()
		asset_filters["asset_category"] = ["in", list(INPUT_ASSET_CATEGORIES)]
		assets = _get_project_selected_assets(frappe.get_doc("Media Project", project.name))
		cover_image = None
		product_asset = next((a for a in assets if a.asset_category == "Product"), None)
		cover_candidates = ([product_asset] if product_asset else []) + [a for a in assets if a != product_asset]
		for a in cover_candidates:
			v = frappe.db.get_value("Asset Version", {"media_asset": a.name}, "file", order_by="version_number desc")
			if v:
				cover_image = v
				break

		project.update(
			{
				"campaign_name": project.project_name,
				"project_count": 1,
				"asset_count": len(assets),
				"cover_image": cover_image,
				"asset_categories": list({a.asset_category for a in assets if a.asset_category}),
			}
		)

	return projects


@frappe.whitelist()
def get_video_styles():
	styles = []
	for row in frappe.get_all("Generation Workflow", fields=["workflow_key"], distinct=True):
		workflow = get_latest_valid_workflow(row.workflow_key)
		if workflow:
			label = " ".join(part.capitalize() for part in workflow.workflow_key.split("_"))
			styles.append(frappe._dict(workflow_key=workflow.workflow_key, client_name=label, client_description=""))
	return sorted(styles, key=lambda style: style.client_name)


@frappe.whitelist()
def get_project_workspace(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	media_specification = get_latest_media_specification(project.name)
	specification_names = _get_project_specification_names(project.name)
	storyboard_specification = _get_latest_project_storyboard_specification(
		project.name, specification_names
	)
	assets = _get_project_assets(project.name)
	outputs = _get_project_outputs(project.name)
	storyboard = []
	production = None
	final_video = None

	if storyboard_specification:
		storyboard = frappe.get_all(
			"Shot Specification",
			filters={"media_specification": storyboard_specification.name},
			fields=[
				"name",
				"shot_number",
				"camera_direction",
				"subject_identity",
				"action_plot",
				"environment",
				"audio_direction",
				"generation_prompt",
				"shot_instructions",
				"planned_frame_count",
				"duration_seconds",
				"selected_output_asset_version",
			],
			order_by="shot_number asc, name asc",
		)
		for shot in storyboard:
			if shot.get("selected_output_asset_version"):
				selected_output = frappe.db.get_value(
					"Asset Version",
					shot["selected_output_asset_version"],
					"file",
				)
				if selected_output:
					shot["selected_output_file"] = selected_output
					shot["output_video"] = selected_output
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

		production = (
			_get_latest_project_generation_run(project.name, [media_specification.name])
			if media_specification
			else None
		)
		if production:
			final_asset_ver_name = getattr(project, "current_output_asset_version", None) or production.final_asset_version
			if final_asset_ver_name:
				final_file = frappe.db.get_value(
					"Asset Version", final_asset_ver_name, "file"
				)
				final_video = {
					"asset_version": final_asset_ver_name,
					"file": final_file,
				}

	return {
		"project": {
			"name": project.name,
			"project_name": project.project_name,
			"product_name": project.product_name,
			"campaign_brief": project.campaign_brief,
			"video_idea": project.video_idea,
			"reference_template": project.reference_template,
			"status": project.status,
			"current_output_asset_version": getattr(project, "current_output_asset_version", None),
			"export_status": getattr(project, "export_status", "Idle") or "Idle",
			"export_error": getattr(project, "export_error", None),
			"export_started_at": getattr(project, "export_started_at", None),
			"export_completed_at": getattr(project, "export_completed_at", None),
		},
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
		"final_video": final_video,
	}


@frappe.whitelist()
def get_project_production(name):
	"""Return the current project production state for lightweight polling."""
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	media_specification = get_latest_media_specification(project.name)
	if not media_specification:
		return None

	production = _get_latest_project_generation_run(project.name, [media_specification.name])
	if not production:
		return None
	jobs = frappe.get_all(
		"Generation Job",
		filters={"generation_run": production.name},
		fields=[
			"name",
			"shot_specification",
			"depends_on_job",
			"status",
			"progress",
			"failure_class",
			"error_summary",
		],
		order_by="creation asc",
	)
	for job in jobs:
		shot = frappe.db.get_value(
			"Shot Specification",
			job.shot_specification,
			["shot_number", "selected_output_asset_version"],
			as_dict=True,
		)
		job["shot_number"] = shot.shot_number if shot else None
		job["selected_output_asset_version"] = (
			shot.selected_output_asset_version if shot else None
		)
		job["output_video"] = (
			frappe.db.get_value(
				"Asset Version", shot.selected_output_asset_version, "file"
			)
			if shot and shot.selected_output_asset_version
			else None
		)
	production["jobs"] = jobs
	final_asset_ver = (
		frappe.db.get_value("Media Project", production.media_project, "current_output_asset_version")
		if production.get("media_project")
		else None
	) or production.final_asset_version
	if final_asset_ver:
		production["final_video"] = {
			"asset_version": final_asset_ver,
			"file": frappe.db.get_value("Asset Version", final_asset_ver, "file"),
		}
	return production


@frappe.whitelist()
def refresh_project_production(name):
	"""Refresh an active project run from ComfyUI before returning its state."""
	project = frappe.get_doc("Media Project", name)
	project._require_write_access()
	media_specification = get_latest_media_specification(project.name)
	if not media_specification:
		return None

	production = _get_latest_project_generation_run(project.name, [media_specification.name])
	if not production:
		return None

	if production.status in ("Queued", "Running"):
		from joymedia.services.generation_orchestrator import refresh_run

		refresh_run(production.name)
		frappe.db.commit()

	return get_project_production(project.name)

def _get_project_assets(media_project):
	"""Return the reference inputs explicitly selected for a project."""
	return _get_project_selected_assets(frappe.get_doc("Media Project", media_project))


def _get_project_selected_assets(project):
	assets = []
	for selection in project.selected_media or []:
		version = frappe.db.get_value(
			"Asset Version",
			selection.asset_version,
			["name", "media_asset", "file"],
			as_dict=True,
		)
		if not version or not version.file:
			continue
		asset = frappe.db.get_value(
			"Media Asset",
			version.media_asset,
			["name", "asset_name", "media_type", "asset_category"],
			as_dict=True,
		)
		if not asset or asset.media_type != "Image":
			continue
		assets.append(
			{
				"name": asset.name,
				"media_asset": asset.name,
				"asset_version": version.name,
				"asset_name": asset.asset_name,
				"media_type": asset.media_type,
				"asset_category": asset.asset_category,
				"file": version.file,
			}
		)

	return assets


@frappe.whitelist()
def get_project_reference_candidates(media_project):
	project = frappe.get_doc("Media Project", media_project)
	project._require_read_access()
	asset_filters = _asset_scope_filters()
	asset_filters.update(
		{
			"media_type": "Image",
			"asset_category": ["in", list(INPUT_ASSET_CATEGORIES)],
		}
	)
	organization_assets = frappe.get_list(
		"Media Asset",
		filters=asset_filters,
		fields=["name", "asset_name", "asset_category"],
		order_by="modified desc",
		limit_page_length=100,
	)
	selected_versions = {asset["asset_version"] for asset in _get_project_selected_assets(project)}

	for asset in organization_assets:
		version = frappe.db.get_value(
			"Asset Version", {"media_asset": asset.name}, ["name", "file"], order_by="version_number desc", as_dict=True
		)
		asset["asset_version"] = version.name if version else None
		asset["file"] = version.file if version else None
		asset["selected"] = bool(asset.asset_version and asset.asset_version in selected_versions)
	return organization_assets


@frappe.whitelist()
def select_project_reference(media_project, asset_name):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()

	source = frappe.get_doc("Media Asset", asset_name)
	if (
		source.status != "Active"
		or source.media_type != "Image"
		or source.asset_category not in INPUT_ASSET_CATEGORIES
	):
		frappe.throw(_("That asset is not available as a reference for this project."))

	asset_version = frappe.db.get_value(
		"Asset Version", {"media_asset": source.name}, ["name", "file"], order_by="version_number desc", as_dict=True
	)
	if not asset_version:
		frappe.throw(_("The selected asset has no file version."))

	if any(
		row.asset_version == asset_version.name
		or frappe.db.get_value("Asset Version", row.asset_version, "file") == asset_version.file
		for row in project.selected_media or []
	):
		return {"asset_version": asset_version.name, "selected": True}
	if any(asset["file"] == asset_version.file for asset in _get_project_selected_assets(project)):
		return {"asset_version": asset_version.name, "selected": True}

	project.append("selected_media", {"asset_version": asset_version.name})
	project.save(ignore_permissions=True)
	frappe.db.commit()
	return {"asset_version": asset_version.name, "selected": True}


@frappe.whitelist()
def remove_project_reference(media_project, asset_version):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	asset_version = frappe.get_doc("Asset Version", asset_version)
	if asset_version.media_asset not in {
		asset["media_asset"] for asset in _get_project_selected_assets(project)
	}:
		frappe.throw(_("That asset is not selected for this project."))

	project.selected_media = [
		row for row in project.selected_media or [] if row.asset_version != asset_version.name
	]
	project.save(ignore_permissions=True)
	frappe.db.commit()
	return {"removed": True}


def _get_project_outputs(media_project):
	"""Return temporary generated artifacts for this project's specifications."""
	specifications = _get_project_specification_names(media_project)
	if not specifications:
		return []
	shots = frappe.get_all("Shot Specification", filters={"media_specification": ["in", specifications]}, pluck="name")
	if not shots:
		return []
	jobs = frappe.get_all("Generation Job", filters={"shot_specification": ["in", shots]}, pluck="name")
	attempts = frappe.get_all("Generation Attempt", filters={"generation_job": ["in", jobs]}, pluck="name")
	if not attempts:
		return []
	return frappe.get_all(
		"Generation Artifact",
		filters={"generation_attempt": ["in", attempts]},
		fields=["name", "artifact_key", "artifact_role", "media_type", "frappe_file", "creation"],
		order_by="creation desc",
		limit_page_length=100,
	)


def _minimum_shot_count(media_specification):
	if not media_specification or not media_specification.workflow:
		return 1

	workflow_version = frappe.get_doc(
		"Generation Workflow", media_specification.workflow
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
def save_project_video_settings(
	project_name,
	total_duration_seconds,
	delivery_preset,
	video_style=None,
	continuity_mode=None,
	global_consistency_instructions=None,
):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	return project.save_video_settings(
		total_duration_seconds,
		delivery_preset,
		video_style,
		continuity_mode,
		global_consistency_instructions,
	)


@frappe.whitelist()
def generate_project_video_plan(project_name):
	project = frappe.get_doc("Media Project", project_name)
	return project.generate_video_plan()


@frappe.whitelist()
def apply_project_video_plan(project_name, plan_json):
	project = frappe.get_doc("Media Project", project_name)
	return project.apply_video_plan(plan_json)


@frappe.whitelist()
def generate_project_video_from_storyboard(project_name):
	project = frappe.get_doc("Media Project", project_name)
	return project.generate_video()


@frappe.whitelist()
def generate_project_video(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	return project.generate_end_to_end()


@frappe.whitelist()
def revise_project_shot_with_ai(project_name, shot_name, instruction):
	from joymedia.services.ai_director import revise_project_shot_with_ai as revise

	return revise(project_name, shot_name, instruction)


@frappe.whitelist()
def apply_project_shot_ai_revision(project_name, shot_name, values, regenerate=False):
	from joymedia.services.ai_director import apply_project_shot_ai_revision as apply_revision

	return apply_revision(project_name, shot_name, values, regenerate)


@frappe.whitelist()
def retry_project_failed_jobs(project_name):
	project = frappe.get_doc("Media Project", project_name)
	return project.retry_failed_jobs()


@frappe.whitelist()
def revise_project_storyboard(project_name, use_current_workflow_defaults=False):
	project = frappe.get_doc("Media Project", project_name)
	return project.create_storyboard_revision(use_current_workflow_defaults)


@frappe.whitelist()
def update_project_shot(project_name, shot_name, values):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot Specification", shot_name)
	media_specification = get_latest_media_specification(project.name)
	if media_specification and media_specification.status == "Draft" and shot.media_specification != media_specification.name:
		_copy_storyboard_shots(
			_get_latest_project_storyboard_specification(project.name), media_specification
		)
		matching_shot = frappe.db.get_value(
			"Shot Specification",
			{"media_specification": media_specification.name, "shot_number": shot.shot_number},
			"name",
		)
		if matching_shot:
			shot = frappe.get_doc("Shot Specification", matching_shot)
	if not media_specification or shot.media_specification != media_specification.name:
		frappe.throw(_("Shot does not belong to the current project revision."))
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
		"shot_instructions",
		"subject_identity",
		"action_plot",
		"camera_direction",
		"environment",
		"audio_direction",
	]
	for f in updatable_fields:
		if f in values:
			setattr(shot, f, values[f])
	# Editing the prompt invalidates the current rendered take. The old take
	# remains available as history, but is no longer the current output.
	shot.selected_output_asset_version = None

	# The generation prompt is derived from the specification and shot instructions. Do
	# not trust a prompt snapshot sent by the browser: it may be stale after a
	# continuous-mode shot is edited.
	# Qwen owns creative prompt generation. Legacy shot-direction fields remain
	# readable for old records but do not create a new execution prompt.
	if "generation_prompt" in values:
		shot.generation_prompt = str(values["generation_prompt"] or "").strip()
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
		"shot_instructions": shot.shot_instructions,
	}


@frappe.whitelist()
def set_project_shot_keyframe(project_name, shot_name, frame_role, asset_version):
	"""Persist a shot's start or end keyframe in its editable storyboard revision."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if frame_role not in ("first_frame", "last_frame"):
		frappe.throw(_("Keyframe role must be first_frame or last_frame."))

	media_specification = get_latest_media_specification(project.name)
	if not media_specification:
		frappe.throw(_("This project has no editable video specification."))
	shot = frappe.get_doc("Shot Specification", shot_name)
	if media_specification.status == "Draft" and shot.media_specification != media_specification.name:
		_copy_storyboard_shots(
			_get_latest_project_storyboard_specification(project.name), media_specification
		)
		matching_shot = frappe.db.get_value(
			"Shot Specification",
			{"media_specification": media_specification.name, "shot_number": shot.shot_number},
			"name",
		)
		if matching_shot:
			shot = frappe.get_doc("Shot Specification", matching_shot)
	if shot.media_specification != media_specification.name:
		frappe.throw(_("Shot does not belong to the current project revision."))
	if media_specification.status != "Draft":
		frappe.throw(_("Create a storyboard revision before changing keyframes."))

	asset = frappe.db.get_value(
		"Asset Version", asset_version, ["name", "media_asset"], as_dict=True
	)
	if not asset:
		frappe.throw(_("The selected keyframe asset does not exist."))
	media_asset = frappe.db.get_value("Media Asset", asset.media_asset, ["media_type"], as_dict=True)
	if not media_asset or media_asset.media_type != "Image":
		frappe.throw(_("The selected keyframe image is not available for this project."))

	shot.set(
		"generation_inputs",
		[
			{"input_role": row.input_role, "asset_version": row.asset_version}
			for row in shot.generation_inputs
			if frappe.scrub(row.input_role or "") != frame_role
		],
	)
	shot.append("generation_inputs", {"input_role": frame_role, "asset_version": asset.name})
	shot.selected_output_asset_version = None
	shot.save(ignore_permissions=True)
	frappe.db.commit()
	return {"shot_name": shot.name, "shot_number": shot.shot_number, "frame_role": frame_role}


@frappe.whitelist()
def update_project_shot_timing(project_name, shot_name, duration_seconds):
	"""Persist one shot's timing while keeping the specification duration fixed."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	try:
		duration_seconds = float(duration_seconds)
	except (TypeError, ValueError):
		frappe.throw(_("Shot duration must be a positive number."))
	if duration_seconds < 1:
		frappe.throw(_("Each shot must be at least 1 second long."))

	media_specification = get_latest_media_specification(project.name)
	if not media_specification:
		frappe.throw(_("This project has no editable video specification."))
	shot = frappe.get_doc("Shot Specification", shot_name)
	if media_specification.status == "Draft" and shot.media_specification != media_specification.name:
		_copy_storyboard_shots(
			_get_latest_project_storyboard_specification(project.name), media_specification
		)
		matching_shot = frappe.db.get_value(
			"Shot Specification",
			{"media_specification": media_specification.name, "shot_number": shot.shot_number},
			"name",
		)
		if matching_shot:
			shot = frappe.get_doc("Shot Specification", matching_shot)
	if shot.media_specification != media_specification.name:
		frappe.throw(_("Shot does not belong to the current project revision."))
	if media_specification.status != "Draft":
		frappe.throw(_("Create a storyboard revision before changing shot timing."))
	shot.selected_output_asset_version = None
	shot.save(ignore_permissions=True)

	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_specification.name},
		fields=["name", "shot_number", "duration_seconds"],
		order_by="shot_number asc, name asc",
	)
	from joymedia.services.shot_duration_planner import rebalance_shot_duration

	result = rebalance_shot_duration(media_specification.name, shot.name, duration_seconds)
	frappe.db.commit()
	return {
		"shot_name": shot.name,
		"shot_number": shot.shot_number,
		**result,
	}


@frappe.whitelist()
def reorder_project_shot(project_name, shot_name, target_shot_number):
	"""Persist a storyboard shot's position in the editable revision."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	try:
		target_shot_number = int(target_shot_number)
	except (TypeError, ValueError):
		frappe.throw(_("Invalid shot position."))
	media_specification = get_latest_media_specification(project.name)
	if not media_specification or media_specification.status != "Draft":
		frappe.throw(_("Create an editable storyboard revision before reordering shots."))
	shot = frappe.get_doc("Shot Specification", shot_name)
	if shot.media_specification != media_specification.name:
		_copy_storyboard_shots(_get_latest_project_storyboard_specification(project.name), media_specification)
		matching = frappe.db.get_value(
			"Shot Specification",
			{"media_specification": media_specification.name, "shot_number": shot.shot_number},
			"name",
		)
		if matching:
			shot = frappe.get_doc("Shot Specification", matching)
	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_specification.name},
		fields=["name", "shot_number"],
		order_by="shot_number asc, name asc",
	)
	if not shots or target_shot_number < 1 or target_shot_number > len(shots):
		frappe.throw(_("Invalid shot position."))
	ordered = [row for row in shots if row.name != shot.name]
	ordered.insert(target_shot_number - 1, next(row for row in shots if row.name == shot.name))
	# Use temporary negative numbers to avoid collisions while reordering.
	for index, row in enumerate(ordered, start=1):
		frappe.db.set_value("Shot Specification", row.name, "shot_number", -index, update_modified=False)
	for index, row in enumerate(ordered, start=1):
		frappe.db.set_value("Shot Specification", row.name, "shot_number", index, update_modified=False)
	frappe.db.commit()
	return {"shot_name": shot.name, "shot_number": target_shot_number}


@frappe.whitelist()
def regenerate_project_shot(project_name, shot_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot Specification", shot_name)
	jobs = frappe.get_all(
		"Generation Job",
		filters={"shot_specification": shot.name},
		fields=["name", "segment_index", "status"],
		order_by="segment_index asc, creation asc",
	)
	if jobs:
		from joymedia.joymedia.doctype.generation_attempt.generation_attempt import (
			create_manual_regeneration_attempt_internal,
			get_effective_attempt,
		)
		from joymedia.services.generation_orchestrator import (
			_retry_and_submit_latest_failed_attempts,
			prepare_chained_regeneration,
		)
		from joymedia.services.generation_runner import submit_attempt

		if any(job.status in ("Queued", "Running") for job in jobs):
			frappe.throw(_("This shot is already running. Stop the current sequence before regenerating it."))
		shot.db_set("selected_output_asset_version", None, update_modified=False)
		first_attempt = get_effective_attempt(jobs[0].name)
		attempt_names = []
		if first_attempt and first_attempt.status == "Completed":
			attempt_names.extend(prepare_chained_regeneration(first_attempt.name))
			first_retry = create_manual_regeneration_attempt_internal(first_attempt.name, "Manual Retry")
			attempt_names.insert(0, first_retry.name)
		elif first_attempt and first_attempt.status == "Failed":
			results = _retry_and_submit_latest_failed_attempts(
				frappe.get_doc("Generation Job", jobs[0].name), "Manual Retry"
			)
			return {"shot_name": shot.name, "attempts": results}
		else:
			frappe.throw(_("Cannot regenerate shot before generating the video."))

		results = []
		for attempt_name in attempt_names:
			submission = submit_attempt(attempt_name)
			results.append({"name": attempt_name, **submission})
		frappe.db.commit()
		return {"shot_name": shot.name, "attempts": results}

	frappe.throw(_("Cannot regenerate shot before generating the video."))


@frappe.whitelist()
def create_draft_project():
	"""Create the minimum editable project and open Studio."""
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be signed in to create a project."))
	if not set(frappe.get_roles()).intersection(
		{"JoyMedia User", "JoyMedia Specialist", "System Manager"}
	):
		frappe.throw(_("You do not have permission to create a project."))
	project = frappe.get_doc(
		{
			"doctype": "Media Project",
			"project_name": "Untitled",
			"product_name": "Untitled",
			"status": "Draft",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"project": project.name}


@frappe.whitelist()
def create_project(
	project_name,
	product_name,
	campaign_brief=None,
	video_idea=None,
	reference_template=None,
):
	if not set(frappe.get_roles()).intersection(
		{"JoyMedia User", "JoyMedia Specialist", "System Manager"}
	):
		frappe.throw(_("You do not have permission to create a project."))
	project = frappe.get_doc(
		{
			"doctype": "Media Project",
			"project_name": project_name,
			"product_name": product_name,
			"campaign_brief": campaign_brief or video_idea,
			"video_idea": video_idea,
			"reference_template": reference_template,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return project


@frappe.whitelist()
@frappe.whitelist()
def get_library_assets(scope=None, asset_type=None):
	filters = {"status": "Active", "asset_scope": "Library"}
	if asset_type == "Images":
		filters["media_type"] = "Image"

	assets = frappe.get_list(
		"Media Asset",
		filters=filters,
		fields=["name", "asset_name", "media_type", "asset_category", "asset_scope", "status", "modified"],
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
	return assets


@frappe.whitelist()
def update_project_name(media_project, project_name):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	project_name = (project_name or "").strip()
	if not project_name:
		frappe.throw(_("Project name cannot be empty."))
	project.project_name = project_name
	project.save(ignore_permissions=True)
	frappe.db.commit()
	return {"project_name": project.project_name}


class MediaProject(Document):
	def _require_read_access(self):
		self._require_owner_access()
		self.check_permission("read")

	def _require_write_access(self):
		self._require_owner_access()
		self.check_permission("write")

	def _require_owner_access(self):
		if frappe.session.user in ("Administrator", "Guest"):
			return
		if "System Manager" in frappe.get_roles():
			return
		if self.owner != frappe.session.user:
			frappe.throw(_("You do not have access to this project."), frappe.PermissionError)

	def before_insert(self):
		self.status = "Draft"

	def validate(self):
		self.project_name = (self.project_name or "").strip()

		if not self.project_name:
			frappe.throw(_("Project Name is required."))

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
			"global_consistency_instructions": media_specification.global_consistency_instructions or "",
			**_customer_style_details(media_specification),
		}

	@frappe.whitelist()
	def save_video_settings(
	self,
	total_duration_seconds,
	delivery_preset,
	video_style=None,
	continuity_mode=None,
	global_consistency_instructions=None,
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
				latest_run_status = frappe.db.get_value(
					"Generation Run",
					{"media_specification": latest.name},
					"status",
					order_by="creation desc",
				)
				if latest_run_status in ("Queued", "Running"):
					frappe.throw(
						_(
							"Video Settings cannot be changed while generation is active. "
							"Wait for the run to finish before changing the format."
						)
					)
				if self.status not in ("Needs Attention", "Completed") and latest_run_status not in (
					"Failed",
				):
					frappe.throw(_("Create a storyboard revision before changing Video Settings."))

				revision = frappe.get_doc(
					{
						"doctype": "Media Specification",
						"media_project": self.name,
						"version_number": (latest.version_number or 0) + 1,
						"status": "Draft",
						"workflow": latest.workflow,
						"video_style": latest.video_style,
						"continuity_mode": latest.continuity_mode,
						"generation_instructions": latest.generation_instructions,
						"global_consistency_instructions": latest.global_consistency_instructions,
						"total_duration_seconds": latest.total_duration_seconds,
						"delivery_preset": latest.delivery_preset,
						"delivery_width": latest.delivery_width,
						"delivery_height": latest.delivery_height,
					}
				).insert(ignore_permissions=True)
				latest = revision

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
				if global_consistency_instructions is not None:
					latest.global_consistency_instructions = global_consistency_instructions
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
			frappe.throw(_("The current project revision is not editable."))
		if not media_specification.workflow:
			frappe.throw(_("Media Specification must have a Workflow."))
		if not self._get_project_image_inputs():
			frappe.throw(_("Add at least one project image before creating a storyboard."))

		workflow_version = frappe.get_doc(
			"Generation Workflow",
			media_specification.workflow,
		)
		product_name = self.product_name

		shot_count = _automatic_shot_count(media_specification, self.name)

		template = None
		if self.reference_template:
			ref = frappe.get_doc("Video Reference Template", self.reference_template)
			template = frappe.parse_json(ref.template_json)

		return generate_video_plan(
			product_name=_meaningful_project_value(
				product_name, "The product shown in the supplied reference image"
			),
			video_idea=_meaningful_project_value(
				self.video_idea,
				"Create a premium cinematic product showcase focused on the supplied product.",
			),
			total_video_duration=media_specification.total_duration_seconds,
			target_fps=workflow_version.output_fps,
			shot_count=shot_count,
			reference_template=template,
			reference_images=self._get_project_image_inputs(),
			video_style=media_specification.video_style or workflow_version.workflow_key,
			generation_mode=media_specification.continuity_mode,
		)

	def _ensure_default_video_specification(self):
		existing = get_latest_media_specification(self.name)
		if existing:
			return existing

		workflow = _get_customer_workflow("product_showcase")
		return frappe.get_doc(
			{
				"doctype": "Media Specification",
				"media_project": self.name,
				"version_number": 1,
				"status": "Draft",
				"workflow": workflow.name,
				"video_style": workflow.workflow_key,
				"continuity_mode": "Continuous",
				"total_duration_seconds": 5,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)

	@frappe.whitelist()
	def generate_end_to_end(self):
		self._require_write_access()
		if not self._get_project_image_inputs():
			frappe.throw(_("Add at least one image before generating a video."))

		media_specification = self._ensure_default_video_specification()
		media_specification.reload()
		if media_specification.status != "Draft":
			latest_run = frappe.db.get_value(
				"Generation Run",
				{"media_specification": media_specification.name},
				["name", "status"],
				as_dict=True,
				order_by="creation desc",
			)
			if latest_run and latest_run.status in ("Queued", "Running"):
				return {"run": latest_run.name, "status": latest_run.status}
			if latest_run and latest_run.status == "Failed":
				# A failed revision is still the user's current generation target.
				# Retry it instead of calling generate_video(), which correctly
				# rejects already-submitted revisions.
				return self.retry_failed_jobs()
			if latest_run and latest_run.status == "Completed":
				return {"run": latest_run.name, "status": latest_run.status}
			frappe.throw(
				_('This storyboard revision has already been submitted. Create a new storyboard revision before generating again.')
			)
		shots = frappe.get_all(
			"Shot Specification",
			filters={"media_specification": media_specification.name},
			pluck="name",
		)
		if not shots:
			plan = self.generate_video_plan()
			from joymedia.services.video_plan_service import apply_video_plan

			apply_video_plan(media_specification.name, plan)
			# Keep a successful storyboard even if renderer preflight fails below.
			frappe.db.commit()

		return self.generate_video()

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
				frappe.throw(_("This project has no Video Settings."))

			media_specification.reload()
			existing_run = frappe.db.get_value(
				"Generation Run",
				{
					"media_specification": media_specification.name,
				"status": ["not in", ["Completed", "Failed", "Cancelled"]],
				},
				["name", "status"],
				as_dict=True,
			)
			if existing_run:
				return {"run": existing_run.name, "status": existing_run.status}
			if media_specification.status != "Draft":
				frappe.throw(_("This project revision has already been submitted."))
			if not self._get_project_image_inputs():
				frappe.throw(_("Add at least one project image before generating a video."))
			if not frappe.db.exists(
				"Shot Specification", {"media_specification": media_specification.name}
			):
				frappe.throw(_("Generate and apply a storyboard first."))
			workflow = frappe.get_doc("Generation Workflow", media_specification.workflow)
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
			frappe.throw(_("This project has no Video Settings."))

		run_name = frappe.db.get_value(
			"Generation Run",
			{
				"media_specification": media_specification.name,
				"status": "Failed",
			},
			"name",
			order_by="creation desc",
		)
		if not run_name:
			frappe.throw(_("This project has no failed video run to retry."))

		# Retries use the workflow attached to the current specification. This
		# lets a repaired workflow revision recover a run created with an
		# obsolete workflow while preserving all old attempts.
		workflow_version_name = media_specification.workflow
		workflow_version = frappe.get_doc("Generation Workflow", workflow_version_name)
		from joymedia.services.workflow_resolver import (
			validate_workflow_bindings,
			validate_workflow_for_execution,
		)

		try:
			validate_workflow_bindings(workflow_version)
			validate_workflow_for_execution(workflow_version)
		except frappe.ValidationError:
			frappe.throw(
				_(
					"Retry is unavailable because the selected Workflow is not a valid "
					"ComfyUI API workflow. Fix the Workflow before retrying."
				)
				)

		current_run_workflow = frappe.db.get_value("Generation Run", run_name, "workflow_version")
		if current_run_workflow != workflow_version_name:
			frappe.db.set_value(
				"Generation Run", run_name, "workflow_version", workflow_version_name, update_modified=False
			)
			for job_name in frappe.get_all(
				"Generation Job",
				filters={
					"generation_run": run_name,
					"status": "Failed",
				},
				pluck="name",
			):
				frappe.db.set_value(
					"Generation Job", job_name, "workflow_version", workflow_version_name, update_modified=False
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
				frappe.throw(_("This project has no Video Settings to revise."))
			if latest.status == "Draft":
				storyboard_source = _get_latest_project_storyboard_specification(self.name)
				if storyboard_source and storyboard_source.name != latest.name:
					_copy_storyboard_shots(storyboard_source, latest)
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
			if self.status not in ("Needs Attention", "Completed") and latest_run_status not in (
				"Failed",
			):
				frappe.throw(_("Storyboard revision is not available in the current project state."))
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
					or frappe.db.get_value("Generation Workflow", workflow, "workflow_key"),
					"total_duration_seconds": latest.total_duration_seconds,
					"delivery_preset": latest.delivery_preset,
					"delivery_width": latest.delivery_width,
					"delivery_height": latest.delivery_height,
					"generation_instructions": latest.generation_instructions,
					"global_consistency_instructions": latest.global_consistency_instructions,
				}
			).insert(ignore_permissions=True)
			_copy_storyboard_shots(latest, revision)

		frappe.db.set_value("Media Project", self.name, "status", "Draft", update_modified=False)
		frappe.db.commit()
		return {"media_specification": revision.name, "version_number": revision.version_number}

	def _get_project_image_inputs(self):
		from joymedia.services.project_image_manifest import get_project_image_manifest

		return get_project_image_manifest(self.name, include_data_url=True)
