# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt


"""HTTP endpoints for project lifecycle, workspace, settings and generation control."""

import frappe
from frappe import _
from joymedia.services.project_context import (
	_aggregate_shot_progress,
	_busy_shots,
	_customer_style_details,
	_get_asset_file_url,
	_get_asset_version_file_url,
	_get_customer_workflow_for_export_quality,
	_get_latest_project_generation_run,
	_get_project_selected_assets,
	_normalize_generation_mode,
	_project_settings,
	normalize_export_quality,
	_remaining_render_minutes,
	_storyboard_payload,
	build_project_snapshot,
)
from joymedia.services.storyboard_job import planning_status


@frappe.whitelist()
def get_project_cards(search=None, status=None, start=0, page_length=24):
	filters = {"status": ["!=", "Archived"]}
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		filters["owner"] = frappe.session.user
	if status and status != "All":
		filters["status"] = status
	try:
		start, page_length = max(0, int(start)), min(100, max(1, int(page_length)))
	except (TypeError, ValueError):
		frappe.throw(_("Invalid project paging."))
	if search:
		search = f"%{str(search).strip()}%"
		search_fields = [
			["Media Project", "project_name", "like", search],
			["Media Project", "product_name", "like", search],
			["Media Project", "video_idea", "like", search],
		]
	else:
		search_fields = None
	projects = frappe.get_list(
		"Media Project",
		filters=filters,
		fields=["name", "project_name", "product_name", "video_idea", "status", "modified"],
		order_by="modified desc",
		limit_start=start,
		limit_page_length=page_length,
		or_filters=search_fields,
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
	count_filters = dict(filters)
	count_filters.pop("project_name", None)
	matching_names = frappe.get_all("Media Project", filters=count_filters, or_filters=search_fields, pluck="name")
	return {
		"items": projects,
		"total": len(matching_names),
		"counts_by_status": {
			status_name: len(frappe.get_all(
				"Media Project", filters={**count_filters, "status": status_name}, or_filters=search_fields, pluck="name"
			))
			for status_name in ("Draft", "Generating", "Needs Attention", "Completed", "Cancelled")
		},
	}


@frappe.whitelist()
def get_sidebar_counts():
	project_filters = {"status": ["!=", "Archived"]}
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		project_filters["owner"] = frappe.session.user
	return {"projects": frappe.db.count("Media Project", filters=project_filters), "assets": frappe.db.count("Media Asset", filters={"status": "Active"})}


@frappe.whitelist()
def archive_project(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if frappe.db.exists(
		"Generation Run",
		{"media_project": project.name, "status": ["in", ["Queued", "Running"]]},
	):
		frappe.throw(_("Stop the active generation before archiving this project."))
	if project.status == "Archived":
		return {"archived": True, "already_archived": True, "project": project.name}
	# Archiving changes only the lifecycle state. Use a targeted update so an
	# older project with a now-removed Select value can still be archived.
	project.db_set("status", "Archived", update_modified=True)
	return {"archived": True, "project": project.name}


@frappe.whitelist()
def get_project_workspace(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	settings = _project_settings(project)
	production = _get_latest_project_generation_run(project.name)
	storyboard = _storyboard_payload(project)
	if production:
		production["shots"] = _aggregate_shot_progress(production.name)
		production["eta_minutes"] = _remaining_render_minutes(production)
		production["scenes"] = [
			{
				"shot": scene["shot"],
				"number": scene["shot_number"],
				"title": scene["shot_name"] or f"Scene {scene['shot_number']}",
				"status": {
					"Waiting": "waiting", "Queued": "queued", "Running": "rendering", "Completed": "ready",
					"Failed": "needs_attention", "Cancelled": "cancelled",
				}.get(scene["status"], "waiting"),
				"progress": scene["progress"],
				"segment_done": scene.get("segment_done", 0),
				"segment_total": scene.get("segment_total", 0),
				"message": scene.get("error_summary") or scene["status"],
			}
			for scene in production["shots"]
		]
		_, current_snapshot_hash = build_project_snapshot(project)
		production["is_outdated"] = bool(
			production.get("project_snapshot_hash") and production.get("project_snapshot_hash") != current_snapshot_hash
		)
	active_run = bool(production and production.status in ("Queued", "Running"))
	current_output_asset_version = project.current_output_asset_version
	final_video = ({
		"asset_version": current_output_asset_version,
		"file": _get_asset_version_file_url(current_output_asset_version),
		"is_outdated": bool(production and production.get("is_outdated")),
		"is_current": not active_run or bool(current_output_asset_version),
		"is_previous_version": False,
		"legacy_non_editable": bool(current_output_asset_version and not storyboard),
	} if current_output_asset_version else None)
	return {
		"project": {
			"name": project.name,
			"project_name": project.project_name,
			"product_name": project.product_name,
			"video_idea": project.video_idea,
			"status": project.status,
			"current_output_asset_version": project.current_output_asset_version,
			"post_production_status": project.post_production_status or "Idle",
			"post_production_step": project.post_production_step or "",
			"post_production_error": project.post_production_error or "",
			"planning_status": planning_status(project.name),
			"busy_shots": _busy_shots(project.name),
			"planning_error": project.planning_error or "",
		},
		"assets": _get_project_selected_assets(project),
		"video_settings": ({
			"name": project.name,
			"duration": settings.total_duration_seconds,
			"delivery_preset": settings.delivery_preset,
			"generation_mode": _normalize_generation_mode(settings.generation_mode),
			"reference_mode": getattr(settings, "reference_mode", None) or "Single Image",
			"quality_mode": getattr(settings, "quality_mode", None) or "Production",
			"global_instructions": settings.global_instructions or "",
			"show_captions": int(settings.show_captions or 0),
			"soundtrack_prompt": settings.soundtrack_prompt or "",
			"export_quality": normalize_export_quality(settings.export_quality),
			**_customer_style_details(settings),
		} if settings.workflow else None),
		"storyboard": storyboard,
		"production": production,
		"final_video": final_video,
	}


@frappe.whitelist()
def refresh_project_studio(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	production = _get_latest_project_generation_run(project.name)
	# The browser polls this endpoint while a render is in progress. Reconcile
	# ComfyUI here as a recovery path as well as in the scheduler: if the worker
	# that normally polls ComfyUI was delayed or restarted, the UI otherwise keeps
	# returning stale task rows (for example 0/2) and the next chained task is
	# never dispatched until the next scheduler tick.
	if production and production.status in ("Queued", "Running"):
		from frappe.utils.synchronization import filelock
		from joymedia.services.generation_orchestrator import refresh_run

		with filelock(f"joymedia-refresh-run-{production.name}"):
			refresh_run(production.name)
	return get_project_workspace(project.name)


@frappe.whitelist()
def get_library_assets(scope=None, asset_type=None, media_type=None):
	filters = {
		"status": "Active",
		"asset_scope": "Library",
		"asset_category": ["not in", ["Shot Output", "Final Deliverable", "Deliverable", "Storyboard"]],
	}
	requested_type = media_type
	if not requested_type and asset_type:
		requested_type = {"Images": "Image", "Videos": "Video", "Audio": "Audio"}.get(asset_type)
	if requested_type:
		filters["media_type"] = requested_type
	assets = frappe.get_list(
		"Media Asset", filters=filters,
		fields=["name", "asset_name", "media_type", "asset_category", "asset_scope", "status", "modified", "media_project"],
		order_by="modified desc", limit_page_length=200,
	)
	filtered_assets = []
	for asset in assets:
		if asset.get("media_project"):
			continue
		version = frappe.db.get_value(
			"Asset Version", {"media_asset": asset.name}, ["name", "file", "analysis_status", "source"],
			order_by="version_number desc", as_dict=True,
		)
		if version and version.source in ("Generated", "Composed"):
			continue
		asset["asset_version"] = version.name if version else None
		asset["file"] = _get_asset_file_url(asset.name, version.file if version else None)
		asset["analysis_status"] = version.analysis_status if version else None
		filtered_assets.append(asset)
	return filtered_assets


@frappe.whitelist()
def create_draft_project():
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be signed in to create a project."))
	if not set(frappe.get_roles()).intersection({"JoyMedia User", "JoyMedia Specialist", "System Manager"}):
		frappe.throw(_("You do not have permission to create a project."))
	project = frappe.get_doc({
		"doctype": "Media Project", "project_name": "Untitled", "product_name": "Untitled", "status": "Draft"
	}).insert(ignore_permissions=True)
	return {"project": project.name}


@frappe.whitelist()
def create_project(project_name, product_name, video_idea=None, campaign_brief=None, reference_template=None):
	"""Create a project. Legacy arguments remain accepted but are not persisted as separate concepts."""
	if not set(frappe.get_roles()).intersection({"JoyMedia User", "JoyMedia Specialist", "System Manager"}):
		frappe.throw(_("You do not have permission to create a project."))
	export_quality = "Draft 720p"
	workflow = _get_customer_workflow_for_export_quality(export_quality)
	from joymedia.services.generation_pipeline_service import pipeline_for_final_workflow
	pipeline = pipeline_for_final_workflow(workflow.name)
	project = frappe.get_doc({
		"doctype": "Media Project",
		"project_name": project_name,
		"product_name": (product_name or "").strip(),
		"video_idea": video_idea or campaign_brief,
		"workflow": workflow.name,
		"generation_pipeline": pipeline.name if pipeline else None,
		"total_duration_seconds": 15,
		"delivery_preset": "Landscape",
		"delivery_width": 1280,
		"delivery_height": 720,
		"export_quality": export_quality,
		"generation_mode": "Continuous",
		# New projects render fast drafts; "Render final" redoes the scenes at full quality.
		"quality_mode": "Draft",
	}).insert(ignore_permissions=True)
	return project


@frappe.whitelist()
def update_project_brief(project_name, product_name=None, video_idea=None):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if product_name is not None:
		project.product_name = str(product_name).strip()
	if video_idea is not None:
		project.video_idea = str(video_idea).strip()
	project.save(ignore_permissions=True)
	return {"project_name": project.name, "product_name": project.product_name, "video_idea": project.video_idea}


@frappe.whitelist()
def update_project_name(media_project, project_name):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	project_name = (project_name or "").strip()
	if not project_name:
		frappe.throw(_("Project name cannot be empty."))
	project.project_name = project_name
	project.save(ignore_permissions=True)
	return {"project_name": project.project_name}


@frappe.whitelist()
def save_project_video_settings(
	project_name, total_duration_seconds, delivery_preset,
	generation_mode=None, global_instructions=None, reference_mode=None,
	quality_mode=None, soundtrack_prompt=None,
	export_quality=None, show_captions=None, workflow=None, generation_pipeline=None,
):
	project = frappe.get_doc("Media Project", project_name)
	return project.save_video_settings(
		total_duration_seconds=total_duration_seconds,
		delivery_preset=delivery_preset,
		generation_mode=generation_mode,
		global_instructions=global_instructions,
		reference_mode=reference_mode,
		quality_mode=quality_mode,
		soundtrack_prompt=soundtrack_prompt,
		export_quality=export_quality,
		show_captions=show_captions,
		workflow=workflow,
		generation_pipeline=generation_pipeline,
	)


@frappe.whitelist()
def generate_project_video(project_name):
	return frappe.get_doc("Media Project", project_name).generate_end_to_end()


@frappe.whitelist()
def retry_project_failed_jobs(project_name):
	return frappe.get_doc("Media Project", project_name).retry_failed_jobs()


@frappe.whitelist()
def cancel_project_generation(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	run = _get_latest_project_generation_run(project.name)
	if not run or run.status not in ("Queued", "Running"):
		return {"cancelled": False, "status": project.status}
	from joymedia.services.generation_orchestrator import cancel_run, sync_media_project_status_for_run
	result = cancel_run(run.name)
	sync_media_project_status_for_run(run.name)
	return {"cancelled": True, **result}
