# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

"""Project domain helpers: snapshot building, asset resolution, run/shot queries.

Shared by the MediaProject controller and the joymedia.api.* endpoint modules so
these read/build routines live in exactly one place.
"""

import hashlib
import json

import frappe
from frappe import _

from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow

SUPPORTED_PROJECT_MEDIA_TYPES = {"Image", "Video", "Audio"}
# Used until enough render jobs have finished to measure the real average.
DEFAULT_RENDER_JOB_MINUTES = 4.5


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
	from joymedia.services.generation_settings import normalize_generation_mode

	return normalize_generation_mode(value)


def _get_customer_workflow(workflow_reference=None):
	"""Resolve an explicitly selected workflow or the configured video default."""
	reference = workflow_reference or frappe.conf.get("joymedia_default_generation_workflow")
	if reference and frappe.db.exists("Generation Workflow", reference):
		return frappe.get_doc("Generation Workflow", reference)
	if reference:
		workflow = get_latest_valid_workflow(reference)
		if workflow:
			return workflow
		frappe.throw(_("No executable Generation Workflow is configured for {0}.").format(reference))
	for row in frappe.get_all(
		"Generation Workflow", filters={"output_media_type": "Video"}, fields=["workflow_key"],
		order_by="modified desc", limit_page_length=100,
	):
		workflow = get_latest_valid_workflow(row.workflow_key)
		if workflow:
			return workflow
	frappe.throw(_("No executable video Generation Workflow is configured."))


def _get_continuation_workflow(workflow):
	from joymedia.services.workflow_resolver import workflow_supports_continuation

	if getattr(workflow, "continuation_workflow", None):
		# The project/run keeps the initial-generation workflow as its public
		# workflow; the orchestrator selects the linked continuation workflow for
		# dependent technical segments.
		return workflow
	if workflow_supports_continuation(workflow):
		return workflow
	for row in frappe.get_all(
		"Generation Workflow", filters={"output_media_type": "Video"}, fields=["workflow_key"],
		order_by="modified desc", limit_page_length=100,
	):
		candidate = get_latest_valid_workflow(row.workflow_key)
		if candidate and workflow_supports_continuation(candidate):
			return candidate
	frappe.throw(_("Continuous generation requires a configured continuation-capable workflow."))


def _meaningful_project_value(value, fallback):
	value = (value or "").strip()
	return value if not is_placeholder_product_name(value) else fallback


def _get_latest_project_generation_run(media_project):
	"""The newest active run, else the newest run: the studio follows work still in progress."""
	for filters in (
		{"media_project": media_project, "status": ["in", ["Queued", "Running"]]},
		{"media_project": media_project},
	):
		rows = _project_runs(filters)
		if rows:
			return rows[0]
	return None


def _busy_shots(media_project):
	"""Scenes with a render still in progress in any of the project's runs."""
	active_runs = frappe.get_all(
		"Generation Run", filters={"media_project": media_project, "status": ["in", ["Queued", "Running"]]}, pluck="name"
	)
	if not active_runs:
		return []
	return sorted(set(frappe.get_all(
		"Generation Task",
		filters={"generation_run": ["in", active_runs], "status": ["not in", ["Completed", "Failed", "Cancelled"]]},
		pluck="shot",
	)))


def _project_runs(filters):
	return frappe.get_all(
		"Generation Run",
		filters=filters,
		fields=[
			"name", "media_project", "status", "started_at", "completed_at",
			"progress", "completed_tasks", "total_tasks", "failed_tasks", "running_tasks",
			"error_summary", "project_snapshot_hash",
		],
		order_by="creation desc",
		limit_page_length=1,
	)


def _build_planning_context(project, settings=None):
	settings = settings or project
	context = {
		"video_idea": project.video_idea or "",
		"product_name": project.product_name or "",
		"selected_asset_versions": sorted(
			row.asset_version for row in project.selected_media or [] if row.asset_version
		),
		"workflow": settings.workflow or "",
		"generation_pipeline": settings.generation_pipeline or "",
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
	reference_mode = getattr(settings, "reference_mode", None) or "Single Image"
	quality_mode = getattr(settings, "quality_mode", None) or "Production"
	return {
		"reference_mode": reference_mode,
		"quality_mode": quality_mode,
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
		"reference_mode": getattr(settings, "reference_mode", None) or "Single Image",
		"quality_mode": getattr(settings, "quality_mode", None) or "Production",
		"generation_mode": settings.generation_mode or "Continuous",
		"global_instructions": settings.global_instructions or "",
		"workflow": settings.workflow or "",
		"generation_pipeline": settings.generation_pipeline or "",
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
		fields=[
			"name", "shot_number", "duration_seconds", "planned_frame_count", "generation_prompt",
			"image_prompt", "motion_plan_json",
			"start_state", "end_state", "handoff_type",
		],
	):
		shot_doc = frappe.get_doc("Shot", shot.name)
		snapshot["shots"].append(
			{
				"shot": shot.name,
				"shot_number": shot.shot_number,
				"duration_seconds": float(shot.duration_seconds or 0),
				"planned_frame_count": int(shot.planned_frame_count or 0),
				"image_prompt": shot.image_prompt or "",
				"generation_prompt": shot.generation_prompt or "",
				"motion_plan_json": shot.motion_plan_json or "",
				"start_state": shot.start_state or "",
				"end_state": shot.end_state or "",
				"handoff_type": shot.handoff_type or "",
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


def _story_film_planning_context(project):
	"""Return (reference contexts, whether references call for director-style planning).

	Reference roles/categories are the semantic source of truth. The project's
	reference_mode is a rendering/input setting and can be stale while a project is
	being edited; it must not route a person+product brief to the generic planner.
	"""
	from joymedia.services.film_director import is_story_film
	from joymedia.services.vision_analysis import ensure_project_image_analysis

	ensure_project_image_analysis(project)
	reference_contexts = _get_project_reference_contexts(project)
	story_film = is_story_film(reference_contexts)
	return reference_contexts, story_film


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
			"caption",
			"duration_seconds",
			"planned_frame_count",
			"selected_output_asset_version",
			"review_status",
		],
	)
	from joymedia.services.scene_takes import take_position

	for shot in shots:
		if shot.selected_output_asset_version:
			shot["output_video"] = _get_asset_version_file_url(shot.selected_output_asset_version)
		shot["take_count"], shot["take_index"] = take_position(specification.name, shot)
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
		# Ordered images the scene is generated from; position N is <Picture N>
		# for Reference-to-Video scenes.
		project_references = {
			selection.asset_version: selection for selection in specification.selected_media or []
		}
		shot["references"] = [
			{
				"asset_version": row.asset_version,
				"file": _get_asset_version_file_url(row.asset_version),
				"input_role": row.reference_role,
				"reference_role": getattr(project_references.get(row.asset_version), "reference_role", None),
				"label": getattr(project_references.get(row.asset_version), "label", None)
				or _asset_version_name(row.asset_version),
			}
			for row in input_rows
			if row.asset_version
		]
	return shots


def _remaining_render_minutes(production):
	"""Rough minutes left for an active run: unfinished render jobs x the recent average job time.

	The GPU is shared, so jobs from other projects can add to this.
	"""
	if production.get("status") not in ("Queued", "Running"):
		return None
	# A failed or dependency-blocked task is not work in ComfyUI's queue.  Counting
	# it here produced a confident ETA even when there was nothing executing.
	remaining = frappe.db.count(
		"Generation Task",
		{"generation_run": production.name, "status": ["in", ["Ready", "Queued", "Running"]]},
	)
	if not remaining:
		return None
	recent = frappe.get_all(
		"Generation Attempt",
		filters={"status": "Completed", "started_at": ["is", "set"], "completed_at": ["is", "set"]},
		fields=["started_at", "completed_at"],
		order_by="completed_at desc",
		limit_page_length=20,
	)
	durations = [
		(row.completed_at - row.started_at).total_seconds() / 60
		for row in recent
		if row.completed_at > row.started_at
	]
	average = sum(durations) / len(durations) if durations else DEFAULT_RENDER_JOB_MINUTES
	return max(1, round(remaining * average))


def _aggregate_shot_progress(run_name):
	jobs = frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name},
		fields=["shot", "status", "progress", "error_summary", "segment_frame_count", "segment_index", "pipeline_step_key"],
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
		# Keep the technical state truthful at the shot boundary.  The client must
		# not turn every unfinished pipeline stage into "Generating": an H3 task
		# waiting for Flux, a task queued at ComfyUI, and a failed keyframe need
		# distinctly different actions in the storyboard.
		if any(status == "Failed" for status in statuses):
			status = "Failed"
		elif any(status == "Running" for status in statuses):
			status = "Running"
		elif any(status == "Queued" for status in statuses):
			status = "Queued"
		elif statuses and all(status == "Completed" for status in statuses):
			status = "Completed"
		elif statuses and all(status == "Cancelled" for status in statuses):
			status = "Cancelled"
		else:
			status = "Waiting"
		total_frames = sum(max(int(row.segment_frame_count or 0), 0) for row in shot_jobs)
		if total_frames:
			progress = sum(
				float(row.progress or 0) * max(int(row.segment_frame_count or 0), 0)
				for row in shot_jobs
			) / total_frames
		else:
			progress = sum(float(row.progress or 0) for row in shot_jobs) / max(len(shot_jobs), 1)
		active_job = next(
			(row for row in shot_jobs if row.status in ("Running", "Queued", "Ready")),
			next((row for row in shot_jobs if row.status == "Failed"), None),
		)
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
			"current_step": active_job.pipeline_step_key if active_job else None,
			"current_step_status": active_job.status if active_job else None,
		})
	return sorted(result, key=lambda row: (row["shot_number"] or 0, row["shot"]))


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


def _asset_version_name(asset_version_name):
	media_asset = frappe.db.get_value("Asset Version", asset_version_name, "media_asset")
	return frappe.db.get_value("Media Asset", media_asset, "asset_name") if media_asset else None


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
