# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import hashlib
import json
import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.synchronization import filelock

from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow


ALLOWED_STATUSES = {"Draft", "Generating", "Completed", "Needs Attention", "Cancelled", "Archived"}
SUPPORTED_PROJECT_MEDIA_TYPES = {"Image", "Video", "Audio"}
DEFAULT_CUSTOMER_WORKFLOW_KEY = "h3_i2v_production"


def is_placeholder_product_name(value):
	return not (value or "").strip() or (value or "").strip().lower() in {
		"untitled", "untitled product", "sản phẩm mới", "new product",
	}


def _planning_shot_count(total_duration_seconds):
	return 1 if float(total_duration_seconds or 0) <= 5 else None


def _plan_append_scene_frames(duration_seconds, fps):
	total_frames = round(float(duration_seconds) * float(fps))
	max_scene_frames = round(5 * float(fps))
	if total_frames < 1 or max_scene_frames < 1:
		frappe.throw(_("Append duration and workflow FPS must be positive."))
	frames = []
	remaining = total_frames
	while remaining > 0:
		current = min(max_scene_frames, remaining)
		frames.append(current)
		remaining -= current
	return frames


def _normalize_generation_mode(value):
	return {"Independent": "Multi-shot", "Chained": "Continuous", "Consistency": "Continuous"}.get(
		value, value or "Multi-shot"
	)


def _get_customer_workflow(video_style=None):
	workflow_key = video_style or DEFAULT_CUSTOMER_WORKFLOW_KEY
	workflow = get_latest_valid_workflow(workflow_key)
	if not workflow:
		frappe.throw(
			_("No executable Generation Workflow is configured for {0}.").format(workflow_key)
		)
	return workflow


def _get_continuation_workflow(workflow):
	from joymedia.services.workflow_resolver import workflow_supports_continuation

	if getattr(workflow, "continuation_workflow", None):
		# The project/run keeps the initial-generation workflow as its public
		# workflow; the orchestrator selects the linked continuation workflow for
		# dependent technical segments.
		return workflow
	if workflow_supports_continuation(workflow):
		return workflow
	continuation_workflow = get_latest_valid_workflow("h3_i2v_production")
	if not continuation_workflow:
		frappe.throw(_("Continuous generation requires a workflow that supports first-frame continuation."))
	return continuation_workflow


def _meaningful_project_value(value, fallback):
	value = (value or "").strip()
	return value if not is_placeholder_product_name(value) else fallback


def _get_latest_project_generation_run(media_project):
	rows = frappe.get_all(
		"Generation Run",
		filters={"media_project": media_project},
		fields=[
			"name", "media_project", "status", "started_at", "completed_at",
			"progress", "completed_tasks", "total_tasks", "failed_tasks", "running_tasks",
			"error_summary", "project_snapshot_hash",
		],
		order_by="creation desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _build_planning_context(project, settings=None):
	settings = settings or project
	context = {
		"video_idea": project.video_idea or "",
		"product_name": project.product_name or "",
		"selected_asset_versions": sorted(
			row.asset_version for row in project.selected_media or [] if row.asset_version
		),
		"workflow": settings.workflow or "",
		"generation_mode": getattr(settings, "generation_mode", None) or "",
		"total_duration_seconds": float(settings.total_duration_seconds or 0),
		"delivery_preset": settings.delivery_preset or "",
		"global_instructions": settings.global_instructions or "",
	}
	serialized = json.dumps(context, sort_keys=True, separators=(",", ":"))
	return context, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _customer_style_details(settings):
	if not settings:
		return {}
	workflow = (
		frappe.db.get_value("Generation Workflow", settings.workflow, ["workflow_key"], as_dict=True)
		if settings.workflow else None
	)
	workflow_name = " ".join(part.capitalize() for part in workflow.workflow_key.split("_")) if workflow else None
	return {
		"video_style": getattr(settings, "video_style", None) or (workflow.workflow_key if workflow else None),
		"video_style_name": workflow_name,
	}


def _project_settings(project):
	"""Return the project-owned generation settings."""
	return project


def _active_project_shots(project_name, fields=None):
	return frappe.get_all(
		"Shot",
		filters={"media_project": project_name, "is_removed": 0},
		fields=fields
			or [
				"name",
				"shot_number",
				"shot_name",
				"duration_seconds",
				"planned_frame_count",
				"generation_prompt",
				"selected_output_asset_version",
			],
		order_by="shot_number asc, name asc",
	)


def build_project_snapshot(project):
	settings = _project_settings(project)
	workflow_fps = frappe.db.get_value("Generation Workflow", settings.workflow, "output_fps") if settings.workflow else None
	snapshot = {
		"media_project": project.name,
		"project_name": project.project_name or "",
		"product_name": project.product_name or "",
		"video_idea": project.video_idea or "",
		"total_duration_seconds": float(settings.total_duration_seconds or 0),
		"delivery_preset": settings.delivery_preset or "",
		"delivery_width": int(settings.delivery_width or 0),
		"delivery_height": int(settings.delivery_height or 0),
		"output_fps": float(workflow_fps or 24),
		"generation_mode": settings.generation_mode or "Multi-shot",
		"global_instructions": settings.global_instructions or "",
		"workflow": settings.workflow or "",
		"references": [
			{
				"asset_version": row.asset_version,
				"reference_key": getattr(row, "reference_key", None) or "",
				"reference_role": row.reference_role or "General",
				"label": row.label or "",
			}
			for row in project.selected_media or []
			if row.asset_version
		],
	}
	snapshot["shots"] = []
	for shot in _active_project_shots(
		project.name,
		fields=["name", "shot_number", "duration_seconds", "planned_frame_count", "generation_prompt"],
	):
		shot_doc = frappe.get_doc("Shot", shot.name)
		snapshot["shots"].append(
			{
				"shot": shot.name,
				"shot_number": shot.shot_number,
				"duration_seconds": float(shot.duration_seconds or 0),
				"planned_frame_count": int(shot.planned_frame_count or 0),
				"generation_prompt": shot.generation_prompt or "",
				"references": [
					{
						"reference_role": row.reference_role or "",
						"asset_version": row.asset_version,
					}
					for row in shot_doc.generation_inputs or []
					if row.reference_role and row.asset_version
				],
			}
		)
	serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
	return serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _get_project_selected_assets(project):
	"""Return project ingredients as immutable Asset Versions, regardless of media type."""
	if isinstance(project, str):
		project = frappe.get_doc("Media Project", project)
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
				reference_key=getattr(selection, "reference_key", None) or "",
				reference_role=selection.reference_role or "General",
				label=selection.label or "",
				asset_name=asset.asset_name,
				media_type=asset.media_type,
				asset_category=asset.asset_category,
				file=_get_asset_file_url(asset.name, version.file),
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
			"reference_role": asset.reference_role,
			"label": asset.label,
			"reference_key": getattr(asset, "reference_key", None) or "",
		}
		if asset.analysis_status == "Ready" and asset.analysis_json:
			try:
				context["analysis"] = frappe.parse_json(asset.analysis_json)
			except (TypeError, ValueError):
				context["analysis"] = asset.analysis_json
		contexts.append(context)
	return contexts


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
	project.status = "Archived"
	project.save(ignore_permissions=True)
	return {"archived": True, "project": project.name}


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
	shots = _active_project_shots(
		specification.name,
		fields=[
			"name",
			"shot_number",
			"shot_name",
			"generation_prompt",
			"duration_seconds",
			"planned_frame_count",
			"selected_output_asset_version",
		],
	)
	for shot in shots:
		if shot.selected_output_asset_version:
			shot["output_video"] = _get_asset_version_file_url(shot.selected_output_asset_version)
		input_rows = frappe.get_all(
			"Shot Reference",
			filters={"parent": shot.name, "parenttype": "Shot"},
			fields=["reference_role", "asset_version"],
			order_by="idx asc",
		)
		for role, output_key in (("first_frame", "reference_image"), ("last_frame", "last_frame_image")):
			row = next((r for r in input_rows if frappe.scrub(r.reference_role or "") == role), None)
			if row:
				shot[output_key] = _get_asset_version_file_url(row.asset_version)
				project_reference = next(
					(
						selection for selection in specification.selected_media or []
						if selection.asset_version == row.asset_version
					),
					None,
				)
				if project_reference and getattr(project_reference, "reference_key", None):
					shot[f"{output_key}_reference_key"] = project_reference.reference_key
	return shots


@frappe.whitelist()
def get_project_workspace(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	settings = _project_settings(project)
	production = _get_latest_project_generation_run(project.name)
	storyboard = _storyboard_payload(project)
	if production:
		production["shots"] = _aggregate_shot_progress(production.name)
		production["scenes"] = [
			{
				"shot": scene["shot"],
				"number": scene["shot_number"],
				"title": scene["shot_name"] or f"Scene {scene['shot_number']}",
				"status": {
					"Pending": "waiting", "Generating": "generating", "Completed": "ready",
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
		},
		"assets": _get_project_selected_assets(project),
		"video_settings": ({
			"name": project.name,
			"duration": settings.total_duration_seconds,
			"delivery_preset": settings.delivery_preset,
			"generation_mode": _normalize_generation_mode(settings.generation_mode),
			"global_instructions": settings.global_instructions or "",
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
	if production and production.status in ("Queued", "Running"):
		from joymedia.services.generation_orchestrator import refresh_run
		with filelock(f"joymedia-refresh-run-{production.name}"):
			refresh_run(production.name)
	return get_project_workspace(project.name)


def _aggregate_shot_progress(run_name):
	jobs = frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name},
		fields=["shot", "status", "progress", "error_summary", "segment_frame_count", "segment_index"],
		order_by="creation asc",
	)
	groups = {}
	for job in jobs:
		groups.setdefault(job.shot, []).append(job)
	result = []
	for shot_name, shot_jobs in groups.items():
		shot = frappe.db.get_value(
			"Shot", shot_name,
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
		total_frames = sum(max(int(row.segment_frame_count or 0), 0) for row in shot_jobs)
		if total_frames:
			progress = sum(
				float(row.progress or 0) * max(int(row.segment_frame_count or 0), 0)
				for row in shot_jobs
			) / total_frames
		else:
			progress = sum(float(row.progress or 0) for row in shot_jobs) / max(len(shot_jobs), 1)
		output = shot.selected_output_asset_version if shot else None
		result.append({
			"shot": shot_name,
			"shot_number": shot.shot_number if shot else None,
			"shot_name": shot.shot_name if shot else None,
			"status": status,
			"progress": progress,
			"error_summary": next((row.error_summary for row in shot_jobs if row.error_summary), None),
			"selected_output_asset_version": output,
			"output_video": _get_asset_version_file_url(output) if output else None,
			"segment_done": sum(1 for row in shot_jobs if row.status == "Completed"),
			"segment_total": len(shot_jobs),
		})
	return sorted(result, key=lambda row: (row["shot_number"] or 0, row["shot"]))


@frappe.whitelist()
def get_project_production(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	production = _get_latest_project_generation_run(project.name)
	if not production:
		return None
	_, current_snapshot_hash = build_project_snapshot(project)
	production["is_outdated"] = bool(
		production.get("project_snapshot_hash") and production.get("project_snapshot_hash") != current_snapshot_hash
	)
	production["shots"] = _aggregate_shot_progress(production.name)
	current_output_asset_version = project.current_output_asset_version
	production["final_video"] = ({
		"asset_version": current_output_asset_version,
		"file": _get_asset_version_file_url(current_output_asset_version),
	} if current_output_asset_version else None)
	return production


@frappe.whitelist()
def refresh_project_production(name):
	project = frappe.get_doc("Media Project", name)
	project._require_read_access()
	production = _get_latest_project_generation_run(project.name)
	if production and production.status in ("Queued", "Running"):
		from joymedia.services.generation_orchestrator import refresh_run
		refresh_run(production.name)
	return get_project_production(project.name)


def _get_asset_file_url(media_asset, file_url):
	"""Return a private file URL tied to the exact Media Asset attachment."""
	if not file_url:
		return None

	# Library files created by older upload flows may not have been attached to
	# the Media Asset, even though Asset Version.file still points at them. A
	# raw /private/files URL is rejected by Frappe unless it includes the file
	# identity (fid), so resolve the file by the immutable URL as a fallback.
	file_name = frappe.db.get_value(
		"File",
		{
			"file_url": file_url,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": media_asset,
		},
		"name",
	)
	if not file_name:
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		return file_url

	return frappe.get_doc("File", file_name).unique_url


def _get_asset_version_file_url(asset_version_name):
	if not asset_version_name:
		return None
	version = frappe.db.get_value(
		"Asset Version",
		asset_version_name,
		["media_asset", "file"],
		as_dict=True,
	)
	if not version:
		return None
	return _get_asset_file_url(version.media_asset, version.file)


@frappe.whitelist()
def get_project_asset_candidates(media_project, media_type=None):
	project = frappe.get_doc("Media Project", media_project)
	project._require_read_access()
	filters = {
		"status": "Active",
		"asset_scope": "Library",
		"asset_category": ["not in", ["Shot Output", "Final Deliverable", "Deliverable", "Storyboard"]],
	}
	if media_type:
		if media_type not in SUPPORTED_PROJECT_MEDIA_TYPES:
			frappe.throw(_("Project references support Image, Video, or Audio assets."))
		filters["media_type"] = media_type
	else:
		filters["media_type"] = ["in", sorted(SUPPORTED_PROJECT_MEDIA_TYPES)]
	assets = frappe.get_list(
		"Media Asset", filters=filters,
		fields=["name", "asset_name", "media_type", "asset_category", "media_project"],
		order_by="modified desc", limit_page_length=200,
	)
	selected = {row.asset_version for row in project.selected_media or [] if row.asset_version}
	valid_assets = []
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
		asset["selected"] = bool(version and version.name in selected)
		valid_assets.append(asset)
	return valid_assets


@frappe.whitelist()
def select_project_asset(media_project, asset_name, reference_role="Product", label=None, reference_key=None):
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
	selected = next((row for row in project.selected_media or [] if row.asset_version == version.name), None)
	if selected:
		selected.reference_role = reference_role or "General"
		selected.label = label or ""
		if reference_key:
			selected.reference_key = reference_key
		project.save(ignore_permissions=True)
		return {"asset_version": version.name, "selected": True}
	project.append(
		"selected_media",
		{
			"asset_version": version.name,
			"reference_key": reference_key or "",
			"reference_role": reference_role or "General",
			"label": label or "",
		},
	)
	project.save(ignore_permissions=True)
	return {"asset_version": version.name, "selected": True}


@frappe.whitelist()
def remove_project_asset(media_project, asset_version):
	project = frappe.get_doc("Media Project", media_project)
	project._require_write_access()
	if not any(row.asset_version == asset_version for row in project.selected_media or []):
		frappe.throw(_("That asset version is not selected for this project."))
	project.set("selected_media", [row for row in project.selected_media or [] if row.asset_version != asset_version])
	project.save(ignore_permissions=True)
	return {"removed": True}


# Compatibility names used by the current Vue client. The domain concept is now
# selected project media, not image-only "references".
@frappe.whitelist()
def get_project_reference_candidates(media_project):
	return get_project_asset_candidates(media_project)


@frappe.whitelist()
def select_project_reference(media_project, asset_name, reference_role="Product", label=None, reference_key=None):
	return select_project_asset(media_project, asset_name, reference_role, label, reference_key)


@frappe.whitelist()
def remove_project_reference(media_project, asset_version):
	return remove_project_asset(media_project, asset_version)


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
	project = frappe.get_doc({
		"doctype": "Media Project",
		"project_name": project_name,
		"product_name": (product_name or "").strip(),
		"video_idea": video_idea or campaign_brief,
		"workflow": _get_customer_workflow().name,
		"total_duration_seconds": 15,
		"delivery_preset": "Landscape",
		"delivery_width": 1920,
		"delivery_height": 1080,
		"generation_mode": "Multi-shot",
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
	project_name, total_duration_seconds, delivery_preset, video_style=None,
	generation_mode=None, global_instructions=None,
):
	project = frappe.get_doc("Media Project", project_name)
	return project.save_video_settings(
		total_duration_seconds,
		delivery_preset,
		video_style,
		generation_mode,
		global_instructions,
	)


@frappe.whitelist()
def generate_project_video(project_name):
	return frappe.get_doc("Media Project", project_name).generate_end_to_end()


@frappe.whitelist()
def append_project_scenes(
	project_name,
	duration_seconds,
	instruction="",
	continuity=True,
	after_shot_name=None,
):
	return frappe.get_doc("Media Project", project_name).append_scenes(
		after_shot_name=after_shot_name,
		duration_seconds=duration_seconds,
		instruction=instruction,
		continuity=continuity,
	)


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


@frappe.whitelist()
def revise_project_storyboard(project_name, instruction=None, use_current_workflow_defaults=False):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	instruction = (instruction or "").strip()
	if not instruction:
		frappe.throw(_("Describe how the storyboard should change."))
	from joymedia.services.shot_duration_planner import ensure_shot_planning_editable
	ensure_shot_planning_editable(project.name)
	from joymedia.services.qwen_client import generate_video_plan
	from joymedia.services.workflow_resolver import get_workflow_input_contract
	workflow = frappe.get_doc("Generation Workflow", project.workflow)
	current_shots = "\n".join(
		f"Scene {shot.shot_number}: {shot.generation_prompt} ({shot.duration_seconds}s)"
		for shot in _active_project_shots(project.name, fields=["shot_number", "generation_prompt", "duration_seconds"])
	)
	plan = generate_video_plan(
		product_name=_meaningful_project_value(project.product_name, "the product"),
		video_idea=f"{project.video_idea or ''}\n\nCURRENT STORYBOARD:\n{current_shots}\n\nREVISION REQUEST:\n{instruction}",
		total_video_duration=float(project.total_duration_seconds or 15),
		target_fps=float(workflow.output_fps or 24),
		reference_media=_get_project_selected_assets(project),
		video_style=workflow.workflow_key,
		generation_mode=_normalize_generation_mode(project.generation_mode),
		global_instructions=project.global_instructions,
		format_preset=project.delivery_preset,
		workflow_input_contract=get_workflow_input_contract(workflow),
	)
	from joymedia.services.video_plan_service import apply_video_plan
	created = apply_video_plan(project.name, plan)
	return {"media_project": project.name, "shots": created}


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
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	if isinstance(values, str):
		values = frappe.parse_json(values)
	if "generation_prompt" in values:
		shot.generation_prompt = str(values["generation_prompt"] or "").strip()
	shot.selected_output_asset_version = None
	shot.save(ignore_permissions=True)
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
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	asset = frappe.db.get_value("Asset Version", asset_version, ["name", "media_asset"], as_dict=True)
	if not asset or frappe.db.get_value("Media Asset", asset.media_asset, "media_type") != "Image":
		frappe.throw(_("Keyframes must use an Image Asset Version."))
	shot.set("generation_inputs", [
				{"reference_role": row.reference_role, "asset_version": row.asset_version}
		for row in shot.generation_inputs or [] if frappe.scrub(row.reference_role or "") != frame_role
	])
	shot.append("generation_inputs", {"reference_role": frame_role, "asset_version": asset.name})
	shot.selected_output_asset_version = None
	shot.save(ignore_permissions=True)
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
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	from joymedia.services.shot_duration_planner import rebalance_shot_duration
	result = rebalance_shot_duration(project.name, shot.name, duration_seconds)
	return {"shot_name": shot.name, "shot_number": shot.shot_number, **result}


def _renumber_active_shots(project_name):
	shots = _active_project_shots(project_name, fields=["name"])
	for index, shot in enumerate(shots, start=1):
		frappe.db.set_value("Shot", shot.name, "shot_number", -index, update_modified=False)
	for index, shot in enumerate(shots, start=1):
		frappe.db.set_value("Shot", shot.name, "shot_number", index, update_modified=False)


def _update_project_duration_from_active_shots(project):
	shots = _active_project_shots(project.name, fields=["duration_seconds"])
	new_duration = sum(float(row.duration_seconds or 0) for row in shots)
	project.db_set("total_duration_seconds", new_duration, update_modified=False)


@frappe.whitelist()
def remove_project_scene(project_name, shot_name, confirm_continuation=False):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if frappe.db.exists(
		"Generation Run",
		{"media_project": project.name, "status": ["in", ["Queued", "Running"]]},
	):
		frappe.throw(_("Scenes cannot be removed while generation is active."))
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Scene does not belong to this project."))
	if shot.is_removed:
		return {"removed": True}

	shot_tasks = frappe.get_all("Generation Task", filters={"shot": shot.name}, pluck="name")
	confirmed = str(confirm_continuation).lower() in ("1", "true", "yes", "on")
	if shot_tasks and not confirmed:
		dependent_task = frappe.db.exists(
			"Generation Task",
			{"depends_on_task": ["in", shot_tasks]},
		)
		if dependent_task:
			return {
				"removed": False,
				"requires_confirmation": True,
				"message": _(
					"This scene has generated continuation scenes. Removing it may create a visible jump."
				),
			}

	from joymedia.services.timeline_editor import _remove_shot_timeline_clips
	_remove_shot_timeline_clips(project.name, shot.name)
	frappe.db.set_value("Shot", shot.name, "is_removed", 1, update_modified=False)
	_renumber_active_shots(project.name)
	_update_project_duration_from_active_shots(project)
	return {"removed": True}


@frappe.whitelist()
def reorder_project_shot(project_name, shot_name, target_shot_number):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	from joymedia.services.shot_duration_planner import ensure_shot_planning_editable
	ensure_shot_planning_editable(project.name)
	try:
		target_shot_number = int(target_shot_number)
	except (TypeError, ValueError):
		frappe.throw(_("Invalid shot position."))
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	shots = _active_project_shots(project.name, fields=["name", "shot_number"])
	if not shots or target_shot_number < 1 or target_shot_number > len(shots):
		frappe.throw(_("Invalid shot position."))
	ordered = [row for row in shots if row.name != shot.name]
	ordered.insert(target_shot_number - 1, next(row for row in shots if row.name == shot.name))
	for index, row in enumerate(ordered, start=1):
		frappe.db.set_value("Shot", row.name, "shot_number", -index, update_modified=False)
	for index, row in enumerate(ordered, start=1):
		frappe.db.set_value("Shot", row.name, "shot_number", index, update_modified=False)
	frappe.db.commit()
	return {"shot_name": shot.name, "shot_number": target_shot_number}


@frappe.whitelist()
def regenerate_project_shot(project_name, shot_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."), frappe.PermissionError)
	if shot.is_removed:
		frappe.throw(_("Removed scenes cannot be regenerated."))
	jobs = frappe.get_all(
		"Generation Task", filters={"shot": shot.name},
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
				frappe.get_doc("Generation Task", jobs[0].name), "Manual Retry"
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
	return {"shot_name": shot.name, "attempts": results}


class MediaProject(Document):
	def _require_read_access(self):
		self._require_owner_access()
		self.check_permission("read")

	def _require_write_access(self):
		self._require_owner_access()
		self.check_permission("write")

	def _require_owner_access(self):
		if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles():
			return
		if self.owner != frappe.session.user:
			frappe.throw(_("You do not have access to this project."), frappe.PermissionError)

	def before_insert(self):
		self.status = "Draft"

	def validate(self):
		self._validate_generation_affecting_changes()
		from joymedia.joymedia.doctype.project_reference.project_reference import assign_reference_key
		for reference in self.selected_media or []:
			assign_reference_key(reference, self)
		self.project_name = (self.project_name or "").strip()
		self.product_name = (self.product_name or "").strip()
		if not self.project_name:
			frappe.throw(_("Project Name is required."))
		if not self.product_name and self.status not in ("Draft",):
			frappe.throw(_("Product Name is required."))
		if self.status not in ALLOWED_STATUSES:
			frappe.throw(_("Invalid Media Project status."))

	def _validate_generation_affecting_changes(self):
		if self.is_new() or not frappe.db.exists("Media Project", self.name):
			return
		if not frappe.db.exists(
			"Generation Run", {"media_project": self.name, "status": ["in", ["Queued", "Running"]]}
		):
			return
		fields = (
			"workflow", "generation_mode", "delivery_preset", "delivery_width",
			"delivery_height", "total_duration_seconds", "global_instructions", "selected_media",
		)
		before = self.get_doc_before_save()
		changed = any(self.has_value_changed(fieldname) for fieldname in fields[:-1])
		if before:
			before_media = [
				(row.asset_version, row.reference_role, row.reference_key, row.label)
				for row in before.selected_media or []
			]
			current_media = [
				(row.asset_version, row.reference_role, row.reference_key, row.label)
				for row in self.selected_media or []
			]
			changed = changed or before_media != current_media
		if changed:
			frappe.throw(
				_("Generation-affecting project settings are read-only while a Generation Run is active. "
				  "Stop the active run or create a new revision first.")
			)

	@frappe.whitelist()
	def get_video_settings(self):
		self._require_read_access()
		settings = _project_settings(self)
		if not settings.workflow:
			return None
		return {
			"name": self.name,
			"version_number": None,
			"status": self.status,
			"total_duration_seconds": settings.total_duration_seconds,
			"delivery_preset": settings.delivery_preset,
			"generation_mode": _normalize_generation_mode(settings.generation_mode),
			"global_instructions": settings.global_instructions or "",
			**_customer_style_details(settings),
		}

	@frappe.whitelist()
	def save_video_settings(
		self, total_duration_seconds, delivery_preset, video_style=None,
		generation_mode=None, global_instructions=None,
	):
		self._require_write_access()
		try:
			total_duration_seconds = float(total_duration_seconds)
		except (TypeError, ValueError):
			frappe.throw(_("Duration must be greater than zero."))
		if not math.isfinite(total_duration_seconds) or not 1 <= total_duration_seconds <= 60:
			frappe.throw(_("Duration must be between 1 and 60 seconds."))
		if delivery_preset not in ("Landscape", "Portrait", "Square"):
			frappe.throw(_("Select Landscape, Portrait, or Square format."))
		generation_mode = _normalize_generation_mode(generation_mode or self.generation_mode or "Multi-shot")
		if generation_mode not in ("Multi-shot", "Continuous"):
			frappe.throw(_("Select Continuous or Multi-shot generation mode."))
		workflow = _get_customer_workflow(video_style or self._customer_workflow_key())
		if generation_mode == "Continuous":
			workflow = _get_continuation_workflow(workflow)
		self.total_duration_seconds = total_duration_seconds
		self.delivery_preset = delivery_preset
		self.generation_mode = generation_mode
		if global_instructions is not None:
			self.global_instructions = global_instructions
		self.workflow = workflow.name
		if delivery_preset == "Landscape":
			self.delivery_width, self.delivery_height = 1920, 1080
		elif delivery_preset == "Portrait":
			self.delivery_width, self.delivery_height = 1080, 1920
		elif delivery_preset == "Square":
			self.delivery_width, self.delivery_height = 1080, 1080
		if self.status != "Archived":
			latest_run = _get_latest_project_generation_run(self.name)
			self.status = {
				"Queued": "Generating", "Running": "Generating", "Completed": "Completed",
				"Failed": "Needs Attention", "Cancelled": "Cancelled",
			}.get(latest_run.status if latest_run else None, "Draft")
		self.save(ignore_permissions=True)
		frappe.db.commit()
		return self.get_video_settings()

	def _customer_workflow_key(self):
		return frappe.db.get_value("Generation Workflow", self.workflow, "workflow_key") if self.workflow else None

	def _get_project_image_inputs(self):
		from joymedia.services.project_image_manifest import get_project_image_manifest
		return get_project_image_manifest(self.name, include_data_url=True)

	def generate_video_plan(self):
		self._require_read_access()
		from joymedia.services.qwen_client import generate_video_plan
		settings = _project_settings(self)
		if not settings.workflow:
			frappe.throw(_("Configure Video Settings before generating a storyboard."))
		image_inputs = self._get_project_image_inputs()
		if not image_inputs:
			frappe.throw(_("Add at least one image reference before creating a storyboard."))
		workflow = frappe.get_doc("Generation Workflow", settings.workflow)
		from joymedia.services.workflow_resolver import get_workflow_input_contract
		return generate_video_plan(
			product_name=_meaningful_project_value(self.product_name, "The supplied product"),
			video_idea=_meaningful_project_value(self.video_idea, "Create a premium cinematic product showcase."),
			total_video_duration=settings.total_duration_seconds,
			target_fps=workflow.output_fps,
			shot_count=(
				len(image_inputs)
				if settings.generation_mode == "Multi-shot"
				else _planning_shot_count(settings.total_duration_seconds)
			),
			reference_images=image_inputs,
			reference_media=_get_project_reference_contexts(self),
			video_style=workflow.workflow_key,
			generation_mode=settings.generation_mode,
			global_instructions=settings.global_instructions,
			format_preset=settings.delivery_preset,
			workflow_input_contract=get_workflow_input_contract(workflow),
		)

	@frappe.whitelist()
	def generate_end_to_end(self):
		self._require_write_access()
		if not self._get_project_image_inputs():
			frappe.throw(_("The active generation workflow requires at least one image reference."))
		if not self.workflow:
			frappe.throw(_("Configure Video Settings before generating a storyboard."))
		_, current_snapshot_hash = build_project_snapshot(self)
		latest_run = frappe.db.get_value(
			"Generation Run", {"media_project": self.name}, ["name", "status"],
			as_dict=True, order_by="creation desc",
		)
		if latest_run and latest_run.status in ("Queued", "Running"):
			return {"run": latest_run.name, "status": latest_run.status}
		if latest_run and latest_run.status == "Failed":
			latest_hash = frappe.db.get_value("Generation Run", latest_run.name, "project_snapshot_hash")
			if latest_hash == current_snapshot_hash:
				return self.retry_failed_jobs()
		if not frappe.db.exists("Shot", {"media_project": self.name, "is_removed": 0}):
			from joymedia.services.video_plan_service import apply_video_plan
			apply_video_plan(self.name, self.generate_video_plan())
			from joymedia.services.shot_duration_planner import recalculate_shot_durations
			recalculate_shot_durations(self.name)
			frappe.db.commit()
		return self.generate_video()

	@frappe.whitelist()
	def generate_video(self):
		self._require_write_access()
		from joymedia.services.generation_orchestrator import start_run_internal, validate_generation_preflight
		from joymedia.services.shot_duration_planner import recalculate_shot_durations
		with filelock(f"joymedia-generate-video-{self.name}"):
			existing = frappe.db.get_value(
				"Generation Run",
				{"media_project": self.name, "status": ["not in", ["Completed", "Failed", "Cancelled"]]},
				["name", "status"], as_dict=True,
			)
			if existing:
				return {"run": existing.name, "status": existing.status}
			if not frappe.db.exists("Shot", {"media_project": self.name, "is_removed": 0}):
				frappe.throw(_("Generate a storyboard first."))
			settings = _project_settings(self)
			if not settings.workflow:
				frappe.throw(_("This project has no active Generation Workflow."))
			workflow = frappe.get_doc("Generation Workflow", settings.workflow)
			recalculate_shot_durations(self.name)
			shots = _active_project_shots(
				self.name,
				fields=["name", "shot_number", "planned_frame_count"],
			)
			validate_generation_preflight(self, workflow, shots, check_comfyui=True)
			project_snapshot_json, project_snapshot_hash = build_project_snapshot(self)
			run = frappe.get_doc({
				"doctype": "Generation Run",
				"media_project": self.name,
				"project_snapshot_json": project_snapshot_json,
				"project_snapshot_hash": project_snapshot_hash,
				"workflow": settings.workflow,
				"requested_by": frappe.session.user,
				"status": "Draft",
			}).insert(ignore_permissions=True)
			result = start_run_internal(run.name)
			frappe.db.commit()
			return {"run": run.name, "status": result["status"]}

	@frappe.whitelist()
	def append_scenes(self, duration_seconds, instruction="", continuity=True, after_shot_name=None):
		self._require_write_access()
		try:
			duration_seconds = float(duration_seconds)
		except (TypeError, ValueError):
			frappe.throw(_("Append duration must be a positive number."))
		if not math.isfinite(duration_seconds) or duration_seconds <= 0:
			frappe.throw(_("Append duration must be a positive number."))
		if duration_seconds > 120:
			frappe.throw(_("Add Scene currently supports up to 120 seconds at a time."))
		continuity = str(continuity).lower() in ("1", "true", "yes", "on")

		from joymedia.services.generation_orchestrator import start_run_internal, validate_generation_preflight
		from joymedia.services.qwen_client import generate_video_plan
		from joymedia.services.video_plan_service import append_video_plan
		from joymedia.services.artifact_service import get_attempt_artifact
		from joymedia.joymedia.doctype.generation_attempt.generation_attempt import get_effective_attempt
		from joymedia.services.workflow_resolver import get_workflow_input_contract

		with filelock(f"joymedia-append-scenes-{self.name}"):
			active = frappe.db.get_value(
				"Generation Run",
				{"media_project": self.name, "status": ["in", ["Queued", "Running"]]},
				["name", "status"],
				as_dict=True,
			)
			if active:
				frappe.throw(_("Generation is already active in run {0}.").format(active.name))
			shots = _active_project_shots(
				self.name,
				fields=["name", "shot_number", "generation_prompt"],
			)
			if not shots:
				frappe.throw(_("Create the first storyboard before appending scenes."))
			last_shot = shots[-1]
			if after_shot_name and after_shot_name != last_shot.name:
				frappe.logger("joymedia.storyboard").warning(
					"Append scene mismatch: requested after %s, current final active shot is %s",
					after_shot_name,
					last_shot.name,
				)
				frappe.throw(_("The storyboard changed since Add Scene was opened. Please reopen Add Scene and try again."))

			previous_task = frappe.get_all(
				"Generation Task",
				filters={"shot": last_shot.name, "status": "Completed"},
				fields=["name", "generation_run", "segment_index"],
				order_by="segment_index desc, modified desc",
				limit=1,
			)
			continuation_from_task = previous_task[0].name if previous_task else None
			if continuity:
				if not continuation_from_task:
					frappe.throw(_("The previous shot has no completed generation task."))
				previous_attempt = get_effective_attempt(continuation_from_task)
				last_frame_artifact = (
					get_attempt_artifact(previous_attempt.name, "Last Frame")
					if previous_attempt and previous_attempt.status == "Completed"
					else None
				)
				if not last_frame_artifact or not last_frame_artifact.frappe_file:
					frappe.throw(_("The previous shot has no usable continuation frame."))

			if not self.workflow:
				frappe.throw(_("Configure Video Settings before appending scenes."))
			workflow = frappe.get_doc("Generation Workflow", self.workflow)
			if continuity:
				continuation_workflow = _get_continuation_workflow(workflow)
				if continuation_workflow.name != workflow.name:
					workflow = continuation_workflow
					self.workflow = workflow.name
					self.save(ignore_permissions=True)
			target_frames = _plan_append_scene_frames(duration_seconds, workflow.output_fps)
			image_inputs = self._get_project_image_inputs()
			if not image_inputs:
				frappe.throw(_("The active generation workflow requires at least one image reference."))
			plan = generate_video_plan(
				product_name=_meaningful_project_value(self.product_name, "The supplied product"),
				video_idea=_meaningful_project_value(self.video_idea, "Create a premium cinematic product showcase."),
				total_video_duration=duration_seconds,
				target_fps=workflow.output_fps,
				shot_count=len(target_frames),
				reference_images=image_inputs,
				reference_media=_get_project_reference_contexts(self),
				video_style=workflow.workflow_key,
				generation_mode="Continuous" if continuity else self.generation_mode,
				global_instructions=self.global_instructions,
				format_preset=self.delivery_preset,
				workflow_input_contract=get_workflow_input_contract(workflow),
				continuation_context={
					"previous_prompt": last_shot.generation_prompt,
					"instruction": str(instruction or "").strip(),
				},
			)
			if len(plan.get("shots") or []) != len(target_frames):
				frappe.throw(_("AI Director returned an unexpected number of scenes."))
			fps = float(workflow.output_fps)
			for shot, frame_count in zip(plan["shots"], target_frames):
				shot["planned_frame_count"] = int(frame_count)
				shot["duration_seconds"] = frame_count / fps
			new_shot_names = append_video_plan(
				self.name,
				plan,
				start_after_shot_number=int(last_shot.shot_number),
			)
			self.total_duration_seconds = float(self.total_duration_seconds or 0) + duration_seconds
			self.save(ignore_permissions=True)
			project_snapshot_json, project_snapshot_hash = build_project_snapshot(self)
			scope = {
				"shot_names": new_shot_names,
				"continuity": continuity,
				"continuation_from_task": continuation_from_task if continuity else None,
			}
			run = frappe.get_doc(
				{
					"doctype": "Generation Run",
					"media_project": self.name,
					"project_snapshot_json": project_snapshot_json,
					"project_snapshot_hash": project_snapshot_hash,
					"execution_scope_json": json.dumps(scope, sort_keys=True),
					"workflow": self.workflow,
					"requested_by": frappe.session.user,
					"status": "Draft",
				}
			).insert(ignore_permissions=True)
			new_shots = frappe.get_all(
				"Shot",
				filters={"name": ["in", new_shot_names]},
				fields=["name", "shot_number", "planned_frame_count"],
			)
			validate_generation_preflight(
				self,
				workflow,
				new_shots,
				check_comfyui=True,
				execution_scope=scope,
			)
			result = start_run_internal(run.name)
			frappe.db.commit()
			return {"run": run.name, "status": result["status"], "shots": new_shot_names}

	@frappe.whitelist()
	def retry_failed_jobs(self):
		self._require_write_access()
		from joymedia.services.generation_orchestrator import retry_failed_jobs_internal
		run_name = frappe.db.get_value(
			"Generation Run", {"media_project": self.name, "status": "Failed"},
			"name", order_by="creation desc",
		)
		if not run_name:
			frappe.throw(_("This project has no failed video run to retry."))
		return retry_failed_jobs_internal(run_name)

	@frappe.whitelist()
	def apply_video_plan(self, plan_json):
		self._require_write_access()
		from joymedia.services.video_plan_service import apply_video_plan, parse_video_plan
		if not _project_settings(self).workflow:
			frappe.throw(_("Configure Video Settings before applying a storyboard."))
		created = apply_video_plan(self.name, parse_video_plan(plan_json))
		frappe.db.commit()
		return {"media_project": self.name, "shots": created}

	@frappe.whitelist()
	def create_storyboard_revision(self, use_current_workflow_defaults=False):
		self._require_write_access()
		if not self.workflow:
			frappe.throw(_("Configure Video Settings before revising the storyboard."))
		frappe.db.set_value("Media Project", self.name, "status", "Draft", update_modified=False)
		frappe.db.commit()
		return {"media_project": self.name, "version_number": None}

	@frappe.whitelist()
	def improve_video_idea(self, current_idea=""):
		self._require_write_access()
		from joymedia.services.ai_director import improve_project_video_idea
		return improve_project_video_idea(self.name, current_idea=current_idea)
