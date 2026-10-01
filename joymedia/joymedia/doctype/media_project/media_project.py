# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.synchronization import filelock

from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow


ALLOWED_STATUSES = {"Draft", "Generating", "Completed", "Needs Attention", "Cancelled"}
SUPPORTED_PROJECT_MEDIA_TYPES = {"Image", "Video", "Audio"}


def _normalize_generation_mode(value):
	return {"Independent": "Multi-shot", "Chained": "Continuous", "Consistency": "Continuous"}.get(
		value, value or "Multi-shot"
	)


def _get_customer_workflow(video_style=None):
	workflow = get_latest_valid_workflow(video_style)
	if not workflow and not video_style:
		workflow = get_latest_valid_workflow()
	if not workflow:
		frappe.throw(_("No executable Generation Workflow is configured."))
	return workflow


def _meaningful_project_value(value, fallback):
	value = (value or "").strip()
	return value if value and value.lower() != "untitled" else fallback


def get_latest_media_specification(media_project):
	rows = frappe.get_all(
		"Media Specification",
		filters={"media_project": media_project},
		fields=["name"],
		order_by="version_number desc, creation desc",
		limit_page_length=1,
	)
	return frappe.get_doc("Media Specification", rows[0].name) if rows else None


def _get_project_specification_names(media_project):
	return frappe.get_all(
		"Media Specification",
		filters={"media_project": media_project},
		pluck="name",
		order_by="version_number desc, creation desc",
	)


def _get_latest_project_storyboard_specification(media_project, specification_names=None):
	for specification_name in specification_names or _get_project_specification_names(media_project):
		if frappe.db.exists("Shot Specification", {"media_specification": specification_name}):
			return frappe.get_doc("Media Specification", specification_name)
	return get_latest_media_specification(media_project)


def _get_latest_project_generation_run(media_project, specification_names=None):
	specification_names = specification_names or _get_project_specification_names(media_project)
	if not specification_names:
		return None
	rows = frappe.get_all(
		"Generation Run",
		filters={"media_specification": ["in", specification_names]},
		fields=[
			"name", "media_specification", "status", "started_at", "completed_at",
			"progress", "completed_jobs", "total_jobs", "failed_jobs", "running_jobs",
			"error_summary", "final_asset_version",
		],
		order_by="creation desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _build_planning_context(project, media_specification):
	context = {
		"video_idea": project.video_idea or "",
		"product_name": project.product_name or "",
		"selected_asset_versions": sorted(
			row.asset_version for row in project.selected_media or [] if row.asset_version
		),
		"workflow": media_specification.workflow or "",
		"continuity_mode": media_specification.continuity_mode or "",
		"total_duration_seconds": float(media_specification.total_duration_seconds or 0),
		"delivery_preset": media_specification.delivery_preset or "",
		"global_instructions": media_specification.global_instructions or "",
	}
	serialized = json.dumps(context, sort_keys=True, separators=(",", ":"))
	return context, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _customer_style_details(media_specification):
	if not media_specification:
		return {}
	workflow = (
		frappe.db.get_value("Generation Workflow", media_specification.workflow, ["workflow_key"], as_dict=True)
		if media_specification.workflow else None
	)
	workflow_name = " ".join(part.capitalize() for part in workflow.workflow_key.split("_")) if workflow else None
	return {
		"video_style": media_specification.video_style or (workflow.workflow_key if workflow else None),
		"video_style_name": workflow_name,
	}


def _get_project_selected_assets(project):
	"""Return project ingredients as immutable Asset Versions, regardless of media type."""
	assets = []
	for selection in project.selected_media or []:
		version = frappe.db.get_value(
			"Asset Version",
			selection.asset_version,
			[
				"name", "media_asset", "file", "width", "height", "duration_seconds", "fps",
				"analysis_status", "analysis_json", "analysis_error",
			],
			as_dict=True,
		)
		if not version or not version.file:
			continue
		asset = frappe.db.get_value(
			"Media Asset",
			version.media_asset,
			["name", "asset_name", "media_type", "asset_category", "asset_scope", "status"],
			as_dict=True,
		)
		if not asset or asset.status != "Active" or asset.media_type not in SUPPORTED_PROJECT_MEDIA_TYPES:
			continue
		assets.append(
			frappe._dict(
				name=asset.name,
				media_asset=asset.name,
				asset_version=version.name,
				asset_name=asset.asset_name,
				media_type=asset.media_type,
				asset_category=asset.asset_category,
				file=version.file,
				width=version.width,
				height=version.height,
				duration_seconds=version.duration_seconds,
				fps=version.fps,
				analysis_status=version.analysis_status,
				analysis_json=version.analysis_json,
				analysis_error=version.analysis_error,
			)
		)
	return assets


def _get_project_reference_contexts(project):
	contexts = []
	for asset in _get_project_selected_assets(project):
		context = {
			"asset_name": asset.asset_name,
			"media_type": asset.media_type,
			"asset_category": asset.asset_category,
		}
		if asset.analysis_status == "Ready" and asset.analysis_json:
			try:
				context["analysis"] = frappe.parse_json(asset.analysis_json)
			except (TypeError, ValueError):
				context["analysis"] = asset.analysis_json
		contexts.append(context)
	return contexts


def _copy_storyboard_shots(source_specification, target_specification):
	if frappe.db.exists("Shot Specification", {"media_specification": target_specification.name}):
		return
	for shot_name in frappe.get_all(
		"Shot Specification",
		filters={"media_specification": source_specification.name},
		pluck="name",
		order_by="shot_number asc, name asc",
	):
		source = frappe.get_doc("Shot Specification", shot_name)
		copy = frappe.get_doc({
			"doctype": "Shot Specification",
			"media_specification": target_specification.name,
			"shot_number": source.shot_number,
			"shot_name": source.shot_name,
			"duration_seconds": source.duration_seconds,
			"generation_prompt": source.generation_prompt,
		})
		for input_row in source.generation_inputs or []:
			copy.append("generation_inputs", {
				"input_role": input_row.input_role,
				"asset_version": input_row.asset_version,
			})
		copy.insert(ignore_permissions=True)


@frappe.whitelist()
def get_project_cards():
	filters = {}
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		filters["owner"] = frappe.session.user
	projects = frappe.get_list(
		"Media Project",
		filters=filters,
		fields=["name", "project_name", "product_name", "video_idea", "status", "modified"],
		order_by="modified desc",
		limit_page_length=100,
	)
	for project in projects:
		assets = _get_project_selected_assets(frappe.get_doc("Media Project", project.name))
		cover = next((a.file for a in assets if a.media_type == "Image" and a.asset_category == "Product"), None)
		if not cover:
			cover = next((a.file for a in assets if a.media_type == "Image"), None)
		project.update({
			"campaign_name": project.project_name,
			"asset_count": len(assets),
			"cover_image": cover,
			"asset_categories": sorted({a.asset_category for a in assets if a.asset_category}),
		})
	return projects


@frappe.whitelist()
def get_video_styles():
	styles = []
	for row in frappe.get_all("Generation Workflow", fields=["workflow_key"], distinct=True):
		workflow = get_latest_valid_workflow(row.workflow_key)
		if workflow:
			styles.append(frappe._dict(
				workflow_key=workflow.workflow_key,
				client_name=" ".join(part.capitalize() for part in workflow.workflow_key.split("_")),
				client_description="",
			))
	return sorted(styles, key=lambda style: style.client_name)


def _storyboard_payload(specification):
	if not specification:
		return []
	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": specification.name},
		fields=["name", "shot_number", "shot_name", "generation_prompt", "duration_seconds", "selected_output_asset_version"],
		order_by="shot_number asc, name asc",
	)
	for shot in shots:
		if shot.selected_output_asset_version:
			shot["output_video"] = frappe.db.get_value("Asset Version", shot.selected_output_asset_version, "file")
		input_rows = frappe.get_all(
			"Shot Input Mapping",
			filters={"parent": shot.name, "parenttype": "Shot Specification"},
			fields=["input_role", "asset_version"],
			order_by="idx asc",
		)
		for role, output_key in (("first_frame", "reference_image"), ("last_frame", "last_frame_image")):
			row = next((r for r in input_rows if frappe.scrub(r.input_role or "") == role), None)
			if row:
				shot[output_key] = frappe.db.get_value("Asset Version", row.asset_version, "file")
	return shots


@frappe.whitelist()
def get_project_workspace(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	specification_names = _get_project_specification_names(project.name)
	media_specification = get_latest_media_specification(project.name)
	storyboard_specification = _get_latest_project_storyboard_specification(project.name, specification_names)
	production = _get_latest_project_generation_run(project.name, [media_specification.name]) if media_specification else None
	final_asset_version = project.current_output_asset_version or (production.final_asset_version if production else None)
	return {
		"project": {
			"name": project.name,
			"project_name": project.project_name,
			"product_name": project.product_name,
			"video_idea": project.video_idea,
			"status": project.status,
			"current_output_asset_version": project.current_output_asset_version,
		},
		"assets": _get_project_selected_assets(project),
		"video_settings": ({
			"name": media_specification.name,
			"version_number": media_specification.version_number,
			"status": media_specification.status,
			"duration": media_specification.total_duration_seconds,
			"delivery_preset": media_specification.delivery_preset,
			"continuity_mode": _normalize_generation_mode(media_specification.continuity_mode),
			"global_instructions": media_specification.global_instructions or "",
			**_customer_style_details(media_specification),
		} if media_specification else None),
		"storyboard": _storyboard_payload(storyboard_specification),
		"production": production,
		"final_video": ({
			"asset_version": final_asset_version,
			"file": frappe.db.get_value("Asset Version", final_asset_version, "file"),
		} if final_asset_version else None),
	}


def _aggregate_shot_progress(run_name):
	jobs = frappe.get_all(
		"Generation Job",
		filters={"generation_run": run_name},
		fields=["shot_specification", "status", "progress", "error_summary"],
		order_by="creation asc",
	)
	groups = {}
	for job in jobs:
		groups.setdefault(job.shot_specification, []).append(job)
	result = []
	for shot_name, shot_jobs in groups.items():
		shot = frappe.db.get_value(
			"Shot Specification", shot_name,
			["shot_number", "shot_name", "selected_output_asset_version"], as_dict=True,
		)
		statuses = [row.status for row in shot_jobs]
		if any(status == "Failed" for status in statuses):
			status = "Failed"
		elif any(status in ("Queued", "Running") for status in statuses):
			status = "Generating"
		elif statuses and all(status == "Completed" for status in statuses):
			status = "Completed"
		elif statuses and all(status == "Cancelled" for status in statuses):
			status = "Cancelled"
		else:
			status = "Pending"
		progress = sum(float(row.progress or 0) for row in shot_jobs) / max(len(shot_jobs), 1)
		output = shot.selected_output_asset_version if shot else None
		result.append({
			"shot_specification": shot_name,
			"shot_number": shot.shot_number if shot else None,
			"shot_name": shot.shot_name if shot else None,
			"status": status,
			"progress": progress,
			"error_summary": next((row.error_summary for row in shot_jobs if row.error_summary), None),
			"selected_output_asset_version": output,
			"output_video": frappe.db.get_value("Asset Version", output, "file") if output else None,
		})
	return sorted(result, key=lambda row: (row["shot_number"] or 0, row["shot_specification"]))


@frappe.whitelist()
def get_project_production(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	media_specification = get_latest_media_specification(project.name)
	if not media_specification:
		return None
	production = _get_latest_project_generation_run(project.name, [media_specification.name])
	if not production:
		return None
	production["shots"] = _aggregate_shot_progress(production.name)
	final_asset_version = project.current_output_asset_version or production.final_asset_version
	production["final_video"] = ({
		"asset_version": final_asset_version,
		"file": frappe.db.get_value("Asset Version", final_asset_version, "file"),
	} if final_asset_version else None)
	return production


@frappe.whitelist()
def refresh_project_production(name):
	project = frappe.get_doc("Media Project", name)
	project._require_write_access()
	media_specification = get_latest_media_specification(project.name)
	if not media_specification:
		return None
	production = _get_latest_project_generation_run(project.name, [media_specification.name])
	if production and production.status in ("Queued", "Running"):
		from joymedia.services.generation_orchestrator import refresh_run
		refresh_run(production.name)
		frappe.db.commit()
	return get_project_production(project.name)


@frappe.whitelist()
def get_project_asset_candidates(media_project, media_type=None):
	project = frappe.get_doc("Media Project", media_project)
	project._require_read_access()
	filters = {"status": "Active", "asset_scope": "Library"}
	if media_type:
		if media_type not in SUPPORTED_PROJECT_MEDIA_TYPES:
			frappe.throw(_("Project references support Image, Video, or Audio assets."))
		filters["media_type"] = media_type
	else:
		filters["media_type"] = ["in", sorted(SUPPORTED_PROJECT_MEDIA_TYPES)]
	assets = frappe.get_list(
		"Media Asset", filters=filters,
		fields=["name", "asset_name", "media_type", "asset_category"],
		order_by="modified desc", limit_page_length=200,
	)
	selected = {row.asset_version for row in project.selected_media or [] if row.asset_version}
	for asset in assets:
		version = frappe.db.get_value(
			"Asset Version", {"media_asset": asset.name}, ["name", "file", "analysis_status"],
			order_by="version_number desc", as_dict=True,
		)
		asset["asset_version"] = version.name if version else None
		asset["file"] = version.file if version else None
		asset["analysis_status"] = version.analysis_status if version else None
		asset["selected"] = bool(version and version.name in selected)
	return assets


@frappe.whitelist()
def select_project_asset(media_project, asset_name):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	asset = frappe.get_doc("Media Asset", asset_name)
	if asset.status != "Active" or asset.asset_scope != "Library" or asset.media_type not in SUPPORTED_PROJECT_MEDIA_TYPES:
		frappe.throw(_("That asset cannot be used as a project reference."))
	version = frappe.db.get_value(
		"Asset Version", {"media_asset": asset.name}, ["name", "file"], order_by="version_number desc", as_dict=True
	)
	if not version or not version.file:
		frappe.throw(_("The selected asset has no usable version."))
	if any(row.asset_version == version.name for row in project.selected_media or []):
		return {"asset_version": version.name, "selected": True}
	project.append("selected_media", {"asset_version": version.name})
	project.save(ignore_permissions=True)
	frappe.db.commit()
	return {"asset_version": version.name, "selected": True}


@frappe.whitelist()
def remove_project_asset(media_project, asset_version):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	if not any(row.asset_version == asset_version for row in project.selected_media or []):
		frappe.throw(_("That asset version is not selected for this project."))
	project.set("selected_media", [row for row in project.selected_media or [] if row.asset_version != asset_version])
	project.save(ignore_permissions=True)
	frappe.db.commit()
	return {"removed": True}


# Compatibility names used by the current Vue client. The domain concept is now
# selected project media, not image-only "references".
@frappe.whitelist()
def get_project_reference_candidates(media_project):
	return get_project_asset_candidates(media_project)


@frappe.whitelist()
def select_project_reference(media_project, asset_name):
	return select_project_asset(media_project, asset_name)


@frappe.whitelist()
def remove_project_reference(media_project, asset_version):
	return remove_project_asset(media_project, asset_version)


@frappe.whitelist()
def get_library_assets(scope=None, asset_type=None, media_type=None):
	filters = {"status": "Active", "asset_scope": "Library"}
	requested_type = media_type
	if not requested_type and asset_type:
		requested_type = {"Images": "Image", "Videos": "Video", "Audio": "Audio"}.get(asset_type)
	if requested_type:
		filters["media_type"] = requested_type
	assets = frappe.get_list(
		"Media Asset", filters=filters,
		fields=["name", "asset_name", "media_type", "asset_category", "asset_scope", "status", "modified"],
		order_by="modified desc", limit_page_length=200,
	)
	for asset in assets:
		version = frappe.db.get_value(
			"Asset Version", {"media_asset": asset.name}, ["name", "file", "analysis_status"],
			order_by="version_number desc", as_dict=True,
		)
		asset["asset_version"] = version.name if version else None
		asset["file"] = version.file if version else None
		asset["analysis_status"] = version.analysis_status if version else None
	return assets


@frappe.whitelist()
def create_draft_project():
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be signed in to create a project."))
	if not set(frappe.get_roles()).intersection({"JoyMedia User", "JoyMedia Specialist", "System Manager"}):
		frappe.throw(_("You do not have permission to create a project."))
	project = frappe.get_doc({
		"doctype": "Media Project", "project_name": "Untitled", "product_name": "Untitled", "status": "Draft"
	}).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"project": project.name}


@frappe.whitelist()
def create_project(project_name, product_name, video_idea=None, campaign_brief=None, reference_template=None):
	"""Create a project. Legacy arguments remain accepted but are not persisted as separate concepts."""
	if not set(frappe.get_roles()).intersection({"JoyMedia User", "JoyMedia Specialist", "System Manager"}):
		frappe.throw(_("You do not have permission to create a project."))
	project = frappe.get_doc({
		"doctype": "Media Project",
		"project_name": project_name,
		"product_name": product_name,
		"video_idea": video_idea or campaign_brief,
	}).insert(ignore_permissions=True)
	frappe.db.commit()
	return project


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


@frappe.whitelist()
def save_project_video_settings(
	project_name, total_duration_seconds, delivery_preset, video_style=None,
	continuity_mode=None, global_instructions=None, global_consistency_instructions=None,
):
	project = frappe.get_doc("Media Project", project_name)
	return project.save_video_settings(
		total_duration_seconds,
		delivery_preset,
		video_style,
		continuity_mode,
		global_instructions if global_instructions is not None else global_consistency_instructions,
	)


@frappe.whitelist()
def generate_project_video(project_name):
	return frappe.get_doc("Media Project", project_name).generate_end_to_end()


@frappe.whitelist()
def retry_project_failed_jobs(project_name):
	return frappe.get_doc("Media Project", project_name).retry_failed_jobs()


@frappe.whitelist()
def revise_project_storyboard(project_name, use_current_workflow_defaults=False):
	return frappe.get_doc("Media Project", project_name).create_storyboard_revision(use_current_workflow_defaults)


@frappe.whitelist()
def revise_project_shot_with_ai(project_name, shot_name, instruction):
	from joymedia.services.ai_director import revise_project_shot_with_ai as revise
	return revise(project_name, shot_name, instruction)


@frappe.whitelist()
def apply_project_shot_ai_revision(project_name, shot_name, values, regenerate=False):
	from joymedia.services.ai_director import apply_project_shot_ai_revision as apply_revision
	return apply_revision(project_name, shot_name, values, regenerate)


# Legacy two-step planning endpoints retained temporarily for current clients.
@frappe.whitelist()
def generate_project_video_plan(project_name):
	return frappe.get_doc("Media Project", project_name).generate_video_plan()


@frappe.whitelist()
def apply_project_video_plan(project_name, plan_json):
	return frappe.get_doc("Media Project", project_name).apply_video_plan(plan_json)


@frappe.whitelist()
def generate_project_video_from_storyboard(project_name):
	return frappe.get_doc("Media Project", project_name).generate_video()


@frappe.whitelist()
def update_project_shot(project_name, shot_name, values):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	media_specification = get_latest_media_specification(project.name)
	if not media_specification:
		frappe.throw(_("This project has no editable video specification."))
	shot = frappe.get_doc("Shot Specification", shot_name)
	if media_specification.status == "Draft" and shot.media_specification != media_specification.name:
		_copy_storyboard_shots(_get_latest_project_storyboard_specification(project.name), media_specification)
		matching = frappe.db.get_value(
			"Shot Specification",
			{"media_specification": media_specification.name, "shot_number": shot.shot_number}, "name",
		)
		if matching:
			shot = frappe.get_doc("Shot Specification", matching)
	if shot.media_specification != media_specification.name or media_specification.status != "Draft":
		frappe.throw(_("Create an editable storyboard revision before changing this shot."))
	if isinstance(values, str):
		values = frappe.parse_json(values)
	if "generation_prompt" in values:
		shot.generation_prompt = str(values["generation_prompt"] or "").strip()
	shot.selected_output_asset_version = None
	shot.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"name": shot.name,
		"shot_number": shot.shot_number,
		"shot_name": shot.shot_name,
		"generation_prompt": shot.generation_prompt,
	}


@frappe.whitelist()
def set_project_shot_keyframe(project_name, shot_name, frame_role, asset_version):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if frame_role not in ("first_frame", "last_frame"):
		frappe.throw(_("Keyframe role must be first_frame or last_frame."))
	media_specification = get_latest_media_specification(project.name)
	if not media_specification:
		frappe.throw(_("This project has no editable video specification."))
	shot = frappe.get_doc("Shot Specification", shot_name)
	if media_specification.status == "Draft" and shot.media_specification != media_specification.name:
		_copy_storyboard_shots(_get_latest_project_storyboard_specification(project.name), media_specification)
		matching = frappe.db.get_value(
			"Shot Specification", {"media_specification": media_specification.name, "shot_number": shot.shot_number}, "name"
		)
		if matching:
			shot = frappe.get_doc("Shot Specification", matching)
	if shot.media_specification != media_specification.name or media_specification.status != "Draft":
		frappe.throw(_("Create an editable storyboard revision before changing keyframes."))
	asset = frappe.db.get_value("Asset Version", asset_version, ["name", "media_asset"], as_dict=True)
	if not asset or frappe.db.get_value("Media Asset", asset.media_asset, "media_type") != "Image":
		frappe.throw(_("Keyframes must use an Image Asset Version."))
	shot.set("generation_inputs", [
		{"input_role": row.input_role, "asset_version": row.asset_version}
		for row in shot.generation_inputs or [] if frappe.scrub(row.input_role or "") != frame_role
	])
	shot.append("generation_inputs", {"input_role": frame_role, "asset_version": asset.name})
	shot.selected_output_asset_version = None
	shot.save(ignore_permissions=True)
	frappe.db.commit()
	return {"shot_name": shot.name, "shot_number": shot.shot_number, "frame_role": frame_role}


@frappe.whitelist()
def update_project_shot_timing(project_name, shot_name, duration_seconds):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	try:
		duration_seconds = float(duration_seconds)
	except (TypeError, ValueError):
		frappe.throw(_("Shot duration must be a positive number."))
	if duration_seconds < 1:
		frappe.throw(_("Each shot must be at least 1 second long."))
	media_specification = get_latest_media_specification(project.name)
	if not media_specification or media_specification.status != "Draft":
		frappe.throw(_("Create an editable storyboard revision before changing shot timing."))
	shot = frappe.get_doc("Shot Specification", shot_name)
	if shot.media_specification != media_specification.name:
		_copy_storyboard_shots(_get_latest_project_storyboard_specification(project.name), media_specification)
		matching = frappe.db.get_value(
			"Shot Specification", {"media_specification": media_specification.name, "shot_number": shot.shot_number}, "name"
		)
		if matching:
			shot = frappe.get_doc("Shot Specification", matching)
	from joymedia.services.shot_duration_planner import rebalance_shot_duration
	result = rebalance_shot_duration(media_specification.name, shot.name, duration_seconds)
	frappe.db.commit()
	return {"shot_name": shot.name, "shot_number": shot.shot_number, **result}


@frappe.whitelist()
def reorder_project_shot(project_name, shot_name, target_shot_number):
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
			"Shot Specification", {"media_specification": media_specification.name, "shot_number": shot.shot_number}, "name"
		)
		if matching:
			shot = frappe.get_doc("Shot Specification", matching)
	shots = frappe.get_all(
		"Shot Specification", filters={"media_specification": media_specification.name},
		fields=["name", "shot_number"], order_by="shot_number asc, name asc",
	)
	if not shots or target_shot_number < 1 or target_shot_number > len(shots):
		frappe.throw(_("Invalid shot position."))
	ordered = [row for row in shots if row.name != shot.name]
	ordered.insert(target_shot_number - 1, next(row for row in shots if row.name == shot.name))
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
		"Generation Job", filters={"shot_specification": shot.name},
		fields=["name", "segment_index", "status"], order_by="segment_index asc, creation asc",
	)
	if not jobs:
		frappe.throw(_("Cannot regenerate a shot before generating the video."))
	if any(job.status in ("Queued", "Running") for job in jobs):
		frappe.throw(_("This shot is already running."))
	from joymedia.joymedia.doctype.generation_attempt.generation_attempt import (
		create_manual_regeneration_attempt_internal, get_effective_attempt,
	)
	from joymedia.services.generation_orchestrator import (
		_retry_and_submit_latest_failed_attempts, prepare_chained_regeneration,
	)
	from joymedia.services.generation_runner import submit_attempt
	shot.db_set("selected_output_asset_version", None, update_modified=False)
	first_attempt = get_effective_attempt(jobs[0].name)
	if first_attempt and first_attempt.status == "Failed":
		return {
			"shot_name": shot.name,
			"attempts": _retry_and_submit_latest_failed_attempts(
				frappe.get_doc("Generation Job", jobs[0].name), "Manual Retry"
			),
		}
	if not first_attempt or first_attempt.status != "Completed":
		frappe.throw(_("Cannot regenerate this shot from its current state."))
	attempt_names = prepare_chained_regeneration(first_attempt.name)
	first_retry = create_manual_regeneration_attempt_internal(first_attempt.name, "Reroll")
	attempt_names.insert(0, first_retry.name)
	results = []
	for attempt_name in attempt_names:
		submission = submit_attempt(attempt_name)
		results.append({"name": attempt_name, **submission})
	frappe.db.commit()
	return {"shot_name": shot.name, "attempts": results}


class MediaProject(Document):
	def _require_read_access(self):
		self._require_owner_access()
		self.check_permission("read")

	def _require_write_access(self):
		self._require_owner_access()
		self.check_permission("write")

	def _require_owner_access(self):
		if frappe.session.user in ("Administrator", "Guest") or "System Manager" in frappe.get_roles():
			return
		if self.owner != frappe.session.user:
			frappe.throw(_("You do not have access to this project."), frappe.PermissionError)

	def before_insert(self):
		self.status = "Draft"

	def validate(self):
		self.project_name = (self.project_name or "").strip()
		self.product_name = (self.product_name or "").strip()
		if not self.project_name:
			frappe.throw(_("Project Name is required."))
		if not self.product_name:
			frappe.throw(_("Product Name is required."))
		if self.status not in ALLOWED_STATUSES:
			frappe.throw(_("Invalid Media Project status."))

	@frappe.whitelist()
	def get_video_settings(self):
		self._require_read_access()
		specification = get_latest_media_specification(self.name)
		if not specification:
			return None
		return {
			"name": specification.name,
			"version_number": specification.version_number,
			"status": specification.status,
			"total_duration_seconds": specification.total_duration_seconds,
			"delivery_preset": specification.delivery_preset,
			"continuity_mode": _normalize_generation_mode(specification.continuity_mode),
			"global_instructions": specification.global_instructions or "",
			**_customer_style_details(specification),
		}

	@frappe.whitelist()
	def save_video_settings(
		self, total_duration_seconds, delivery_preset, video_style=None,
		continuity_mode=None, global_instructions=None,
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
			continuity_mode = _normalize_generation_mode(continuity_mode)
			if continuity_mode not in ("Multi-shot", "Continuous"):
				frappe.throw(_("Select Continuous or Multi-shot generation mode."))

		with filelock(f"joymedia-video-settings-{self.name}"):
			latest = get_latest_media_specification(self.name)
			if latest and latest.status != "Draft":
				active_status = frappe.db.get_value(
					"Generation Run", {"media_specification": latest.name}, "status", order_by="creation desc"
				)
				if active_status in ("Queued", "Running"):
					frappe.throw(_("Video Settings cannot change while generation is active."))
				revision = frappe.get_doc({
					"doctype": "Media Specification",
					"media_project": self.name,
					"version_number": (latest.version_number or 0) + 1,
					"status": "Draft",
					"workflow": latest.workflow,
					"video_style": latest.video_style,
					"continuity_mode": latest.continuity_mode,
					"global_instructions": latest.global_instructions,
					"total_duration_seconds": latest.total_duration_seconds,
					"delivery_preset": latest.delivery_preset,
				}).insert(ignore_permissions=True)
				# Settings changes require a fresh planning snapshot/storyboard.
				revision.db_set("planning_context_json", None, update_modified=False)
				revision.db_set("planning_context_hash", None, update_modified=False)
				latest.status = "Superseded"
				latest.save(ignore_permissions=True)
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
				if global_instructions is not None:
					latest.global_instructions = global_instructions
				latest.save(ignore_permissions=True)
				specification = latest
			else:
				specification = frappe.get_doc({
					"doctype": "Media Specification",
					"media_project": self.name,
					"version_number": 1,
					"status": "Draft",
					"workflow": workflow.name,
					"video_style": workflow.workflow_key,
					"continuity_mode": continuity_mode,
					"global_instructions": global_instructions,
					"total_duration_seconds": total_duration_seconds,
					"delivery_preset": delivery_preset,
				}).insert(ignore_permissions=True)

		frappe.db.set_value("Media Project", self.name, "status", "Draft", update_modified=False)
		frappe.db.commit()
		return self.get_video_settings()

	def _get_project_image_inputs(self):
		from joymedia.services.project_image_manifest import get_project_image_manifest
		return get_project_image_manifest(self.name, include_data_url=True)

	def generate_video_plan(self):
		self._require_read_access()
		from joymedia.services.qwen_client import generate_video_plan
		specification = get_latest_media_specification(self.name)
		if not specification or specification.status != "Draft":
			frappe.throw(_("Create or revise Video Settings before generating a storyboard."))
		if not specification.workflow:
			frappe.throw(_("Media Specification must have a Workflow."))
		image_inputs = self._get_project_image_inputs()
		if not image_inputs:
			frappe.throw(_("Add at least one image reference before creating a storyboard."))
		workflow = frappe.get_doc("Generation Workflow", specification.workflow)
		return generate_video_plan(
			product_name=_meaningful_project_value(self.product_name, "The supplied product"),
			video_idea=_meaningful_project_value(self.video_idea, "Create a premium cinematic product showcase."),
			total_video_duration=specification.total_duration_seconds,
			target_fps=workflow.output_fps,
			shot_count=None,
			reference_images=image_inputs,
			reference_media=_get_project_reference_contexts(self),
			video_style=specification.video_style or workflow.workflow_key,
			generation_mode=specification.continuity_mode,
			global_instructions=specification.global_instructions,
			format_preset=specification.delivery_preset,
		)

	def _ensure_default_video_specification(self):
		existing = get_latest_media_specification(self.name)
		if existing:
			return existing
		workflow = _get_customer_workflow("product_showcase")
		return frappe.get_doc({
			"doctype": "Media Specification",
			"media_project": self.name,
			"version_number": 1,
			"status": "Draft",
			"workflow": workflow.name,
			"video_style": workflow.workflow_key,
			"continuity_mode": "Continuous",
			"total_duration_seconds": 5,
			"delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)

	def _ensure_current_planning_specification(self, specification):
		context, context_hash = _build_planning_context(self, specification)
		if specification.planning_context_hash == context_hash:
			return specification
		has_shots = frappe.db.exists("Shot Specification", {"media_specification": specification.name})
		if specification.status == "Draft" and not has_shots and not specification.planning_context_hash:
			specification.planning_context_json = json.dumps(context, sort_keys=True, indent=2)
			specification.planning_context_hash = context_hash
			specification.save(ignore_permissions=True)
			return specification
		previous = specification
		revision = frappe.get_doc({
			"doctype": "Media Specification",
			"media_project": self.name,
			"version_number": (previous.version_number or 0) + 1,
			"status": "Draft",
			"workflow": previous.workflow,
			"video_style": previous.video_style,
			"continuity_mode": previous.continuity_mode,
			"global_instructions": previous.global_instructions,
			"total_duration_seconds": previous.total_duration_seconds,
			"delivery_preset": previous.delivery_preset,
			"audio_cues": [
				{
					"role": row.role,
					"asset_version": row.asset_version,
					"start_seconds": row.start_seconds,
					"end_seconds": row.end_seconds,
					"gain_db": row.gain_db,
					"fade_in_seconds": row.fade_in_seconds,
					"fade_out_seconds": row.fade_out_seconds,
					"duck_others": row.duck_others,
				}
				for row in (previous.audio_cues or [])
			],
			"planning_context_json": json.dumps(context, sort_keys=True, indent=2),
			"planning_context_hash": context_hash,
		}).insert(ignore_permissions=True)
		if previous.status != "Superseded":
			previous.status = "Superseded"
			previous.save(ignore_permissions=True)
		frappe.db.commit()
		return revision

	@frappe.whitelist()
	def generate_end_to_end(self):
		self._require_write_access()
		if not self._get_project_image_inputs():
			frappe.throw(_("The active generation workflow requires at least one image reference."))
		specification = self._ensure_default_video_specification()
		specification.reload()
		specification = self._ensure_current_planning_specification(specification)
		specification.reload()
		if specification.status != "Draft":
			latest_run = frappe.db.get_value(
				"Generation Run", {"media_specification": specification.name}, ["name", "status"],
				as_dict=True, order_by="creation desc",
			)
			if latest_run and latest_run.status in ("Queued", "Running", "Completed"):
				return {"run": latest_run.name, "status": latest_run.status}
			if latest_run and latest_run.status == "Failed":
				return self.retry_failed_jobs()
			frappe.throw(_("This project revision has already been submitted."))
		if not frappe.db.exists("Shot Specification", {"media_specification": specification.name}):
			from joymedia.services.video_plan_service import apply_video_plan
			apply_video_plan(specification.name, self.generate_video_plan())
			frappe.db.commit()
		return self.generate_video()

	@frappe.whitelist()
	def generate_video(self):
		self._require_write_access()
		from joymedia.services.generation_orchestrator import start_run_internal, validate_generation_preflight
		with filelock(f"joymedia-generate-video-{self.name}"):
			specification = get_latest_media_specification(self.name)
			if not specification:
				frappe.throw(_("This project has no Video Settings."))
			existing = frappe.db.get_value(
				"Generation Run",
				{"media_specification": specification.name, "status": ["not in", ["Completed", "Failed", "Cancelled"]]},
				["name", "status"], as_dict=True,
			)
			if existing:
				return {"run": existing.name, "status": existing.status}
			if specification.status != "Draft":
				frappe.throw(_("This project revision has already been submitted."))
			if not frappe.db.exists("Shot Specification", {"media_specification": specification.name}):
				frappe.throw(_("Generate a storyboard first."))
			workflow = frappe.get_doc("Generation Workflow", specification.workflow)
			shots = frappe.get_all(
				"Shot Specification", filters={"media_specification": specification.name},
				fields=["name", "shot_number", "planned_frame_count"], order_by="shot_number asc, name asc",
			)
			validate_generation_preflight(specification, workflow, shots, check_comfyui=True)
			specification.status = "Ready"
			specification.save(ignore_permissions=True)
			run = frappe.get_doc({
				"doctype": "Generation Run",
				"media_specification": specification.name,
				"requested_by": frappe.session.user,
				"status": "Draft",
			}).insert(ignore_permissions=True)
			result = start_run_internal(run.name)
			frappe.db.commit()
			return {"run": run.name, "status": result["status"]}

	@frappe.whitelist()
	def retry_failed_jobs(self):
		self._require_write_access()
		from joymedia.services.generation_orchestrator import retry_failed_jobs_internal
		specification = get_latest_media_specification(self.name)
		if not specification:
			frappe.throw(_("This project has no Video Settings."))
		run_name = frappe.db.get_value(
			"Generation Run", {"media_specification": specification.name, "status": "Failed"},
			"name", order_by="creation desc",
		)
		if not run_name:
			frappe.throw(_("This project has no failed video run to retry."))
		return retry_failed_jobs_internal(run_name)

	@frappe.whitelist()
	def apply_video_plan(self, plan_json):
		self._require_write_access()
		from joymedia.services.video_plan_service import apply_video_plan, parse_video_plan
		specification = get_latest_media_specification(self.name)
		if not specification:
			frappe.throw(_("Create Video Settings before applying a storyboard."))
		created = apply_video_plan(specification.name, parse_video_plan(plan_json))
		frappe.db.commit()
		return {"media_specification": specification.name, "shots": created}

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
				return {"media_specification": latest.name, "version_number": latest.version_number}
			if isinstance(use_current_workflow_defaults, str):
				use_current_workflow_defaults = frappe.parse_json(use_current_workflow_defaults)
			workflow = latest.workflow
			if use_current_workflow_defaults:
				current = get_latest_valid_workflow(latest.video_style)
				if not current:
					frappe.throw(_("No executable workflow is configured."))
				workflow = current.name
			revision = frappe.get_doc({
				"doctype": "Media Specification",
				"media_project": self.name,
				"version_number": (latest.version_number or 0) + 1,
				"status": "Draft",
				"workflow": workflow,
				"video_style": latest.video_style or frappe.db.get_value("Generation Workflow", workflow, "workflow_key"),
				"continuity_mode": latest.continuity_mode,
				"global_instructions": latest.global_instructions,
				"total_duration_seconds": latest.total_duration_seconds,
				"delivery_preset": latest.delivery_preset,
			}).insert(ignore_permissions=True)
			_copy_storyboard_shots(latest, revision)
			context, context_hash = _build_planning_context(self, revision)
			revision.db_set("planning_context_json", json.dumps(context, sort_keys=True, indent=2), update_modified=False)
			revision.db_set("planning_context_hash", context_hash, update_modified=False)
			latest.status = "Superseded"
			latest.save(ignore_permissions=True)
		frappe.db.set_value("Media Project", self.name, "status", "Draft", update_modified=False)
		frappe.db.commit()
		return {"media_specification": revision.name, "version_number": revision.version_number}
