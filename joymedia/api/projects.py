# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt


"""HTTP endpoints for project lifecycle, workspace, settings and generation control."""

import frappe
from frappe import _
from joymedia.services.project.context import (
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
from joymedia.services.planning.jobs import planning_status


@frappe.whitelist()
def get_project_cards(search=None, status=None, start=0, page_length=24):
	from joymedia.services.project.versions import card_rows

	result = card_rows(search, status, start, page_length)
	for project in result["items"]:
		assets = _get_project_selected_assets(frappe.get_doc("Media Project", project["open_project"]))
		cover = next(
			(a.file for a in assets if a.media_type == "Image" and a.asset_category == "Product"), None
		)
		if not cover:
			cover = next((a.file for a in assets if a.media_type == "Image"), None)
		project.update(
			campaign_name=project["project_name"],
			asset_count=len(assets),
			cover_image=cover,
			asset_categories=sorted({a.asset_category for a in assets if a.asset_category}),
		)
	return result


@frappe.whitelist()
def get_sidebar_counts():
	from joymedia.services.partners import is_reviewer, policy

	if is_reviewer():
		access = policy(required=False)
		if not access or not access.allow_generation:
			return {"projects": 0, "assets": 0}
		return {
			"projects": frappe.db.count(
				"Media Project", {"owner": frappe.session.user, "status": ["!=", "Archived"]}
			),
			"assets": frappe.db.count("Media Asset", {"owner": frappe.session.user, "status": "Active"}),
		}
	project_filters = {"status": ["!=", "Archived"], "version_of": ["is", "not set"]}
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		project_filters["owner"] = frappe.session.user
	return {
		"projects": frappe.db.count("Media Project", filters=project_filters),
		"assets": frappe.db.count("Media Asset", filters={"status": "Active"}),
	}


@frappe.whitelist()
def archive_project(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access(allow_archived=True)
	from joymedia.services.project.versions import assert_idle, family, members

	root = family(project)
	if root.name != project.name and root.get("current_edit") == project.name:
		frappe.throw(_("Choose another working edit before archiving this one."))
	assert_idle(members(root) if root.name == project.name else [project.name])
	if project.status == "Archived":
		return {"archived": True, "already_archived": True, "project": project.name}
	# Archiving changes only the lifecycle state. Use a targeted update so an
	# older project with a now-removed Select value can still be archived.
	project.db_set("status", "Archived", update_modified=True)
	return {"archived": True, "project": project.name}


@frappe.whitelist()
def restore_project(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access(allow_archived=True)
	from joymedia.services.project.versions import family

	root = family(project)
	if root.name != project.name and root.status == "Archived":
		frappe.throw(_("Restore the parent project first."))
	if project.status == "Archived":
		project.db_set("status", "Draft")
	return {"project": project.name, "restored": True}


@frappe.whitelist()
def get_project_workspace(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	from joymedia.services.project.versions import summary

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
					"Waiting": "waiting",
					"Queued": "queued",
					"Running": "rendering",
					"Completed": "ready",
					"Failed": "needs_attention",
					"Cancelled": "cancelled",
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
			production.get("project_snapshot_hash")
			and production.get("project_snapshot_hash") != current_snapshot_hash
		)
	active_run = bool(production and production.status in ("Queued", "Running"))
	current_output_asset_version = project.current_output_asset_version
	final_video = (
		{
			"asset_version": current_output_asset_version,
			"file": _get_asset_version_file_url(current_output_asset_version),
			"is_outdated": bool(production and production.get("is_outdated")),
			"is_current": not active_run or bool(current_output_asset_version),
			"is_previous_version": False,
			"legacy_non_editable": bool(current_output_asset_version and not storyboard),
		}
		if current_output_asset_version
		else None
	)
	if final_video:
		from joymedia.services.project.versions import exported_edit_is_outdated
		frozen = frappe.db.get_value('Asset Version', current_output_asset_version, 'edit_manifest_json')
		outdated = exported_edit_is_outdated(project, frozen)
		if outdated is not None:
			final_video['is_outdated'] = outdated
		# A reviewed set of current scene takes is not evidence that an older
		# review MP4 was exported through the release checks.
		final_video["export_purpose"] = (
			"release"
			if frappe.db.get_value("Asset Version", current_output_asset_version, "release_evidence_json")
			else "review"
		)
		pending_brand = [
			s.name
			for s in storyboard
			if s.get("brand_review", {}).get("required") and s["brand_review"]["status"] != "Approved"
		]
		final_video["brand_review_status"] = (
			"Needs Review" if pending_brand else "Approved" if storyboard else "Not Reviewed"
		)
		final_video["brand_review_pending_shots"] = pending_brand
	return {
		"family": summary(project),
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
			"can_guide_motion": frappe.conf.get("joymedia_guided_video_enabled", True) is True
			and bool((frappe.conf.get("joymedia_workflows") or {}).get("guided_video")),
			"planning_error": project.planning_error or "",
			"storyboard_approval_status": project.storyboard_approval_status or "Draft",
			"follows_sheet": project.follows_sheet(),
			"storyboard_timing_warnings": frappe.parse_json(project.storyboard_timing_warnings or "[]"),
		},
		"assets": _get_project_selected_assets(project),
		"video_settings": (
			{
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
				"character_mode": project.character_mode or "Draw in scene",
				"soundtrack_mode": project.soundtrack_mode or "Sound effects only",
				"planning_mode": project.planning_mode or "Creative",
				**_customer_style_details(settings),
			}
			if settings.workflow
			else None
		),
		"storyboard": storyboard,
		"production": production,
		"final_video": final_video,
	}


@frappe.whitelist()
def refresh_project_studio(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	# A newer completed take must not hide an older active run. Reconcile one
	# active run per poll to keep HTTP work bounded; the scheduler also polls all.
	active = frappe.get_all("Generation Run", filters={"media_project": project.name, "status": ["in", ["Queued", "Running"]]}, fields=["name", "status"], order_by="creation asc", limit=1)
	production = active[0] if active else None
	# The browser polls this endpoint while a render is in progress. Reconcile
	# ComfyUI here as a recovery path as well as in the scheduler: if the worker
	# that normally polls ComfyUI was delayed or restarted, the UI otherwise keeps
	# returning stale task rows (for example 0/2) and the next chained task is
	# never dispatched until the next scheduler tick.
	if production and production.status in ("Queued", "Running"):
		from frappe.utils.file_lock import LockTimeoutError
		from frappe.utils.synchronization import filelock
		from joymedia.services.generation.orchestrator import refresh_run

		try:
			# Never wait on a worker that holds the run (a slow upload): it is reconciling already, so show what is
			# stored now instead of failing the page after 30 s.
			with filelock(f"joymedia-refresh-run-{production.name}", timeout=0):
				refresh_run(production.name)
		except LockTimeoutError:
			frappe.clear_last_message()
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
		"Media Asset",
		filters=filters,
		fields=[
			"name",
			"asset_name",
			"media_type",
			"asset_category",
			"asset_scope",
			"status",
			"modified",
			"media_project",
		],
		order_by="modified desc",
		limit_page_length=200,
	)
	filtered_assets = []
	for asset in assets:
		if asset.get("media_project"):
			continue
		version = frappe.db.get_value(
			"Asset Version",
			{"media_asset": asset.name},
			["name", "file", "analysis_status", "source"],
			order_by="version_number desc",
			as_dict=True,
		)
		if version and version.source in ("Generated", "Composed"):
			continue
		asset["asset_version"] = version.name if version else None
		asset["file"] = _get_asset_file_url(asset.name, version.file if version else None)
		asset["analysis_status"] = version.analysis_status if version else None
		filtered_assets.append(asset)
	return filtered_assets


@frappe.whitelist()
def create_project(project_name, product_name, video_idea=None, campaign_brief=None, reference_template=None):
	"""Create a project. Legacy arguments remain accepted but are not persisted as separate concepts."""
	from joymedia.services.partners import is_reviewer, require_generation

	if is_reviewer():
		require_generation()
	if not set(frappe.get_roles()).intersection(
		{"JoyMedia User", "JoyMedia Specialist", "System Manager", "JoyMedia Reviewer"}
	):
		frappe.throw(_("You do not have permission to create a project."))
	export_quality = "Draft 720p"
	# Creating/editing a project must remain available on a fresh development
	# site. Rendering still fails closed later until an administrator promotes a
	# pipeline; draft creation must not select a candidate or newest workflow.
	try:
		workflow = _get_customer_workflow_for_export_quality(export_quality)
	except frappe.ValidationError as exc:
		if "No active Generation Pipeline is configured" not in str(exc):
			raise
		workflow = None
	from joymedia.services.workflows.pipeline import pipeline_for_final_workflow

	pipeline = pipeline_for_final_workflow(workflow.name) if workflow else None
	project = frappe.get_doc(
		{
			"doctype": "Media Project",
			"project_name": project_name,
			"product_name": (product_name or "").strip(),
			"video_idea": video_idea or campaign_brief,
			"workflow": workflow.name if workflow else None,
			"generation_pipeline": pipeline.name if pipeline else None,
			"total_duration_seconds": 15,
			"delivery_preset": "Landscape",
			"delivery_width": 1280,
			"delivery_height": 720,
			"export_quality": export_quality,
			"generation_mode": "Continuous",
			# New projects render a fast draft; export uses the current editable timeline.
			"quality_mode": "Draft",
		}
	).insert(ignore_permissions=True)
	return project


@frappe.whitelist()
def update_project_brief(project_name, product_name=None, video_idea=None):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if product_name is not None:
		project.product_name = str(product_name).strip()
	if video_idea is not None and str(video_idea).strip() != (project.video_idea or "").strip():
		project._refuse_if_sheet()
		project.video_idea = str(video_idea).strip()
	project.save(ignore_permissions=True)
	return {
		"project_name": project.name,
		"product_name": project.product_name,
		"video_idea": project.video_idea,
	}


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
	project_name,
	total_duration_seconds,
	delivery_preset,
	generation_mode=None,
	global_instructions=None,
	reference_mode=None,
	quality_mode=None,
	soundtrack_prompt=None,
	export_quality=None,
	show_captions=None,
	workflow=None,
	generation_pipeline=None,
	character_mode=None,
	soundtrack_mode=None,
	planning_mode=None,
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
		character_mode=character_mode,
		soundtrack_mode=soundtrack_mode,
		planning_mode=planning_mode,
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
	active_runs = frappe.get_all(
		"Generation Run",
		filters={"media_project": project.name, "status": ["in", ["Queued", "Running"]]},
		pluck="name",
		order_by="creation asc",
	)
	if not active_runs:
		return {"cancelled": False, "status": project.status}
	from joymedia.services.generation.orchestrator import cancel_run, sync_media_project_status_for_run

	# Several per-scene takes can be active at once; Stop applies to the project.
	results = [cancel_run(name) for name in active_runs]
	sync_media_project_status_for_run(active_runs[-1])
	return {"cancelled": True, **results[-1], "runs": [result["name"] for result in results]}
