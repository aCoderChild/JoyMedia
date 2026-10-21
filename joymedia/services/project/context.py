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

SUPPORTED_PROJECT_MEDIA_TYPES = {"Image", "Video", "Audio", "Document"}
# Used until enough render jobs have finished to measure the real average.
DEFAULT_RENDER_JOB_MINUTES = 4.5
DEFAULT_EXPORT_QUALITY = "Draft 720p"
VALID_EXPORT_QUALITIES = {"Draft 720p", "Studio 1440p60"}
LEGACY_EXPORT_QUALITIES = {"Standard 1080p": DEFAULT_EXPORT_QUALITY}


def is_placeholder_product_name(value):
	return not (value or "").strip() or (value or "").strip().lower() in {
		"untitled",
		"untitled product",
		"sản phẩm mới",
		"new product",
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
	from joymedia.services.project.modes import normalize_generation_mode

	return normalize_generation_mode(value)


def _get_customer_workflow(workflow_reference=None):
	"""Resolve only a configured workflow document, never the newest candidate."""
	reference = workflow_reference or frappe.conf.get("joymedia_default_generation_workflow")
	if reference and frappe.db.exists("Generation Workflow", reference):
		return frappe.get_doc("Generation Workflow", reference)
	if reference:
		frappe.throw(_("Configured Generation Workflow {0} does not exist.").format(reference))
	from joymedia.services.workflows.pipeline import get_active_generation_pipeline

	return frappe.get_doc("Generation Workflow", get_active_generation_pipeline().steps[-1].workflow)


def normalize_export_quality(value):
	"""Return a supported delivery tier while keeping existing projects usable."""
	value = LEGACY_EXPORT_QUALITIES.get(value, value)
	return value if value in VALID_EXPORT_QUALITIES else DEFAULT_EXPORT_QUALITY


def _get_customer_workflow_for_export_quality(export_quality=None):
	"""Delivery quality changes export settings, never the configured generation pipeline."""
	return _get_customer_workflow()


def _get_continuation_workflow(workflow):
	from joymedia.services.workflows.resolver import workflow_supports_continuation

	if getattr(workflow, "continuation_workflow", None):
		# The project/run keeps the initial-generation workflow as its public
		# workflow; the orchestrator selects the linked continuation workflow for
		# dependent technical segments.
		return workflow
	if workflow_supports_continuation(workflow):
		return workflow
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
	"""Reserve scenes as soon as a run is queued, including task preparation.

	Workers may not have created any tasks yet. Looking only at task rows leaves
	an admission gap in which two tabs can queue the same scene twice.
	"""
	runs = frappe.get_all(
		"Generation Run",
		filters={"media_project": media_project, "status": ["in", ["Queued", "Running"]]},
		fields=["name", "execution_scope_json"],
	)
	if not runs:
		return []
	valid = set(
		frappe.get_all("Shot", filters={"media_project": media_project, "is_removed": 0}, pluck="name")
	)
	busy = set(
		frappe.get_all(
			"Generation Task",
			filters={
				"generation_run": ["in", [run.name for run in runs]],
				"status": ["not in", ["Completed", "Failed", "Cancelled"]],
			},
			pluck="shot",
		)
	)
	for run in runs:
		try:
			scope = frappe.parse_json(run.execution_scope_json or "{}")
		except (TypeError, ValueError):
			scope = {}
		names = scope.get("shot_names") if isinstance(scope, dict) else None
		busy.update(
			names
			if isinstance(names, list) and names and all(isinstance(name, str) for name in names)
			else valid
		)
	return sorted(busy & valid)


def _project_runs(filters):
	return frappe.get_all(
		"Generation Run",
		filters=filters,
		fields=[
			"name",
			"media_project",
			"status",
			"started_at",
			"completed_at",
			"progress",
			"completed_tasks",
			"total_tasks",
			"failed_tasks",
			"running_tasks",
			"error_summary",
			"project_snapshot_hash",
		],
		order_by="creation desc",
		limit_page_length=1,
	)


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


def build_project_snapshot(project, *, require_production_pipeline=False):
	settings = _project_settings(project)
	configured_pipeline = settings.generation_pipeline or ""
	# A run may carry a project-level pipeline only when its immutable final stage
	# matches the project's configured final-stage workflow. Per-shot snapshots
	# validate the same promoted pipeline and record their reference bindings.
	if configured_pipeline:
		from joymedia.services.workflows.pipeline import get_pipeline_steps

		steps = get_pipeline_steps(configured_pipeline)
		if not steps or steps[-1].workflow != settings.workflow:
			configured_pipeline = ""
	if not configured_pipeline and settings.workflow:
		# A project without an explicit pin inherits the pipeline once, when its
		# snapshot is created. Every route in that run then receives this same
		# immutable pipeline version rather than resolving the active setting again.
		from joymedia.services.workflows.pipeline import get_active_generation_pipeline, get_pipeline_steps

		try:
			active_pipeline = get_active_generation_pipeline()
		except frappe.ValidationError as exc:
			if require_production_pipeline or "No active Generation Pipeline is configured" not in str(exc):
				raise
			active_pipeline = None
		if not active_pipeline:
			# Draft planning intentionally has no executable route until an
			# operator promotes a pipeline.
			active_pipeline = None
		else:
			steps = get_pipeline_steps(active_pipeline.name)
			if not steps or steps[-1].workflow != settings.workflow:
				frappe.throw(
					_("The active Generation Pipeline does not end with this project's Generation Workflow.")
				)
			configured_pipeline = active_pipeline.name
	workflow_fps = (
		frappe.db.get_value("Generation Workflow", settings.workflow, "output_fps")
		if settings.workflow
		else None
	)
	default_workflow = (
		frappe.get_doc("Generation Workflow", settings.workflow)
		if settings.workflow and frappe.db.exists("Generation Workflow", settings.workflow)
		else None
	)
	visual_asset_versions = {
		asset.asset_version for asset in _get_project_selected_assets(project) if asset.media_type == "Image"
	}
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
		"soundtrack_mode": getattr(settings, "soundtrack_mode", None) or "Sound effects only",
		"global_instructions": settings.global_instructions or "",
		"workflow": settings.workflow or "",
		"generation_pipeline": configured_pipeline,
		"references": [
			{
				"asset_version": row.asset_version,
				"reference_key": getattr(row, "reference_key", None) or "",
				"identity_key": getattr(row, "identity_key", None)
				or getattr(row, "reference_key", None)
				or "",
				"reference_role": row.reference_role or "General",
				"label": row.label or "",
				"scale": float(getattr(row, "relative_size", None) or 1),
				"keep_rule": getattr(row, "keep_rule", None) or "",
			}
			for row in project.selected_media or []
			if row.asset_version in visual_asset_versions
		],
	}
	from joymedia.services.scene.direction import authored_action

	sheet_scenes = _sheet_scenes(project)
	snapshot["shots"] = []
	for shot in _active_project_shots(
		project.name,
		fields=[
			"name",
			"shot_number",
			"duration_seconds",
			"planned_frame_count",
			"generation_prompt",
			"image_prompt",
			"setting_prompt",
			"motion_plan_json",
			"start_state",
			"end_state",
			"handoff_type",
			"continuity_mode",
		],
	):
		shot_doc = frappe.get_doc("Shot", shot.name)
		from joymedia.services.keyframes.stage import approved_keyframe_task

		shot_snapshot = {
			"shot": shot.name,
			"beat_name": shot_doc.get("storyboard_beat") or shot_doc.get("shot_name"),
			"shot_number": shot.shot_number,
			"duration_seconds": float(shot.duration_seconds or 0),
			"planned_frame_count": int(shot.planned_frame_count or 0),
			"image_prompt": shot.image_prompt or "",
			"setting_prompt": getattr(shot, "setting_prompt", None) or "",
			# A split screen's views (keyframes.overlay.split_screen_keyframe); empty for a full-frame scene.
			"views_json": shot_doc.get("views_json") or "",
			"character_mode": _valid_character_mode(getattr(shot_doc, "character_mode", None))
			or _valid_character_mode(getattr(settings, "character_mode", None))
			or "Draw in scene",
			# An approved, current keyframe is the scene's first frame; its image stage is not repeated.
			"keyframe_task": approved_keyframe_task(shot_doc),
			"keyframe_artifact": shot_doc.keyframe_artifact if approved_keyframe_task(shot_doc) else None,
			"generation_prompt": shot.generation_prompt or "",
			"authored_action": authored_action(
				shot_doc, sheet_scenes.get((shot_doc.storyboard_beat or "", shot_doc.source_timing or ""))
			),
			"motion_plan_json": shot.motion_plan_json or "",
			"start_state": shot.start_state or "",
			"end_state": shot.end_state or "",
			"handoff_type": shot.handoff_type or "",
			"continuity_mode": getattr(shot, "continuity_mode", None) or "New Scene",
			"references": [
				{
					"reference_role": row.reference_role or "",
					"asset_version": row.asset_version,
				}
				for row in shot_doc.generation_inputs or []
				if row.reference_role and row.asset_version
			],
		}
		if default_workflow:
			from joymedia.services.workflows.routing import resolve_shot_render_route

			route = resolve_shot_render_route(
				default_workflow,
				shot_snapshot["references"],
				handoff_type=(
					"new_scene"
					if shot_snapshot["continuity_mode"] == "New Scene"
					else shot_snapshot["handoff_type"]
				),
				motion_plan_json=shot_snapshot["motion_plan_json"],
				pipeline_name=configured_pipeline or None,
			)
			shot_snapshot.update(
				{
					"workflow": route["workflow"],
					"generation_pipeline": route["generation_pipeline"],
					"render_strategy": route["strategy"],
					"routing_reason": route["reason"],
					"requires_recomposition": route["requires_recomposition"],
					"references": route["references"],
				}
			)
			snapshot["shots"].append(shot_snapshot)
	from joymedia.services.consistency.retention import policy
	from joymedia.services.intake.references import preservation_modes

	preservation = preservation_modes(project)
	for reference in snapshot["references"]:
		if reference.get("asset_version") in preservation:
			reference["preservation_mode"] = preservation[reference["asset_version"]]
	retention_policy = policy()
	for scene in snapshot["shots"]:
		for reference in scene.get("references", []):
			if reference.get("asset_version") in preservation:
				reference["preservation_mode"] = preservation[reference["asset_version"]]
		if retention_policy:
			scene["reference_retention"] = retention_policy
			from joymedia.services.consistency.retention import route_presentation

			route_presentation(scene, retention_policy)
	_compose_end_card(snapshot["shots"])
	from joymedia.services.editing.graphics import requested_graphics

	for scene in snapshot["shots"]:
		duration = float(scene.get("planned_frame_count") or 0) / float(snapshot.get("output_fps") or 24)
		scene["graphic_overlays"] = requested_graphics(
			project.get("storyboard_source_json"),
			scene.get("beat_name"),
			scene.get("generation_prompt"),
			duration,
		)
		from joymedia.services.scene.identity import identity_plan
		from joymedia.services.workflows.capabilities import controls

		# Source identities and workflow controls are immutable run inputs, not
		# claims that the output has passed identity or packaging acceptance.
		selected = {r["asset_version"]: r for r in snapshot["references"]}
		references = [
			{**selected.get(r.get("asset_version"), {}), **r} for r in scene.get("references") or []
		]
		scene["consistency_plan"] = identity_plan(
			references,
			controls(frappe.get_doc("Generation Workflow", scene.get("workflow") or snapshot["workflow"])),
		)
	from joymedia.services.planning.camera import camera_planning_rules, reference_camera_grammar
	from joymedia.services.review.admission import freeze_policy

	# Freeze reference direction at the same boundary as workflows and subjects.
	# Both H3 and plain prompt compilation consume this model-independent policy.
	if camera_planning_rules(project):
		snapshot["cinematic_camera"] = True
		snapshot["camera_grammar"] = reference_camera_grammar(project)
	admission = freeze_policy()
	if admission:
		snapshot["visual_admission"] = admission
		for scene in snapshot["shots"]:
			scene["visual_admission_required"] = True
	serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
	return serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _compose_end_card(shots):
	"""The film's last scene, when it shows the product, is laid out by rules instead of drawn by the image model.

	A generated scene leaves composition to a model and can obscure the product. An advertisement ends on the product,
	so its source-art protection remains independent of the actor performance. Hold only the final two seconds;
	never replace a requested wave or pose transition with a whole-shot source card.
	"""
	if not shots:
		return
	last = max(shots, key=lambda row: int(row.get("shot_number") or 0))
	from joymedia.services.planning.shot_structure import structure_for

	structure = structure_for(last)
	if structure and structure["subject_motion"] == "locomotion":
		return  # Preserve the authored performance through the ending; no forced pose hold.
	if any(
		frappe.scrub(row.get("reference_role") or "") == "product" for row in last.get("references") or []
	):
		from joymedia.services.consistency.retention import is_static_presentation

		static = is_static_presentation(last)
		duration = float(last.get("duration_seconds") or 0)
		if not static and duration <= 2:
			raise ValueError(
				"A closing product action needs more than two seconds to leave a readable final hold."
			)
		last["closing_hold_seconds"] = min(2.0, duration)
		last["closing_hold_mode"] = "source_artwork" if static else "generated_pose"
		if static and not last.get("character_mode"):
			last["character_mode"] = "Paste exact art"


def _valid_character_mode(value):
	"""A character mode the pipeline knows, else None (an empty or unknown value means "use the project's")."""
	return value if value in ("Draw in scene", "Paste exact art") else None


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
				"name",
				"media_asset",
				"file",
				"width",
				"height",
				"duration_seconds",
				"fps",
				"analysis_status",
				"analysis_json",
				"analysis_error",
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
				identity_key=getattr(selection, "identity_key", None)
				or getattr(selection, "reference_key", None)
				or "",
				reference_role=selection.reference_role or "General",
				label=selection.label or "",
				relative_size=float(getattr(selection, "relative_size", None) or 1),
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
	from joymedia.services.intake.vision import ensure_project_image_analysis
	from joymedia.services.planning.film_director import (
		infer_product_reference_contexts,
		is_story_film,
	)

	ensure_project_image_analysis(project)
	reference_contexts = _get_project_reference_contexts(project)
	reference_contexts = infer_product_reference_contexts(reference_contexts, project.video_idea)
	story_film = is_story_film(reference_contexts)
	return reference_contexts, story_film


def _get_project_reference_contexts(project):
	from joymedia.services.scene.references import canonical_reference_rows

	contexts = []
	for asset in canonical_reference_rows(_get_project_selected_assets(project)):
		context = {
			"asset_name": asset.asset_name,
			"media_type": asset.media_type,
			"asset_category": asset.asset_category,
			"reference_role": asset.reference_role,
			"label": asset.label,
			"reference_key": getattr(asset, "reference_key", None) or "",
			"identity_key": getattr(asset, "identity_key", None)
			or getattr(asset, "reference_key", None)
			or "",
		}
		if asset.analysis_status == "Ready" and asset.analysis_json:
			try:
				context["analysis"] = frappe.parse_json(asset.analysis_json)
			except (TypeError, ValueError):
				context["analysis"] = asset.analysis_json
		contexts.append(context)
	return contexts


def scene_direction(prompt):
	"""The plain direction of a scene from its video prompt: what happens and the camera, without the audio line, the
	reviewer's corrections block or anything else written for the model."""
	from joymedia.services.review.comments import strip_corrections

	first = next(
		(
			part
			for part in strip_corrections(prompt).split("\n\n")
			if part.strip() and not part.lstrip().startswith("Audio:")
		),
		"",
	)
	action, _sep, camera = first.partition(" Camera: ")
	return {"action": action.strip(), "camera": camera.strip()}


def _sheet_scenes(project):
	"""The imported sheet's scenes by (beat name, timing), when the project was imported from one."""
	try:
		demo = (frappe.parse_json(project.get("storyboard_source_json") or "{}") or {}).get(
			"selected_demo"
		) or {}
	except (TypeError, ValueError):
		return {}
	return {
		(scene.get("beat_name") or "", scene.get("source_timing") or ""): scene
		for scene in demo.get("scenes") or []
	}


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
			"image_prompt",
			"motion_plan_json",
			"storyboard_beat",
			"storyboard_action",
			"source_timing",
			"source_start_seconds",
			"source_end_seconds",
			"continuity_mode",
			"voice_over",
			"audio_cues",
			"caption",
			"duration_seconds",
			"planned_frame_count",
			"selected_output_asset_version",
			"keyframe_artifact",
			"consistency_status",
			"consistency_notes",
			"brand_approval_signature",
			"brand_approved_by",
			"brand_approved_at",
			"illustration",
		],
	)
	from joymedia.services.generation.takes import take_position
	from joymedia.services.review.comments import open_comment_counts

	open_comments = open_comment_counts(specification.name)
	sheet = _sheet_scenes(specification)

	for shot in shots:
		# What the scene shows, in plain words under its frame: the sheet's own words, and the English direction.
		shot["direction"] = scene_direction(shot.generation_prompt)
		from joymedia.services.scene.direction import authored_action

		scene = sheet.get((shot.storyboard_beat or "", shot.source_timing or ""))
		shot["authored_action"] = authored_action(shot, scene)
		from joymedia.services.review.lineage import take_direction_changed

		shot["is_outdated"] = take_direction_changed(shot)
		from joymedia.services.scene.contract import read_contract

		try:
			contract = read_contract(shot.get("motion_plan_json"), shot.duration_seconds)
			from joymedia.services.scene.structure import structure_claims

			shot["continuity_checks"] = list(
				dict.fromkeys(
					[
						*structure_claims(contract),
						*(row["claim"] for row in (contract or {}).get("checks", [])),
					]
				)
			)
		except (TypeError, ValueError):
			shot["continuity_checks"] = []
		shot.pop("motion_plan_json", None)
		shot.pop("image_prompt", None)
		shot.pop("keyframe_artifact", None)
		scene = sheet.get((shot.storyboard_beat or "", shot.source_timing or ""))
		shot["sheet_direction"] = (
			{"action": scene.get("action") or "", "camera": scene.get("visual_camera") or ""}
			if scene
			else None
		)
		if shot.selected_output_asset_version:
			shot["output_video"] = _get_asset_version_file_url(shot.selected_output_asset_version)
		shot["take_count"], shot["take_index"] = take_position(specification.name, shot)
		shot["open_comments"] = open_comments.get(shot.name, 0)
		input_rows = frappe.get_all(
			"Shot Reference",
			filters={"parent": shot.name, "parenttype": "Shot"},
			fields=["reference_role", "asset_version"],
			order_by="idx asc",
		)
		from joymedia.services.review.brand import review_state

		shot["brand_review"] = review_state(shot, input_rows)
		shot.pop("brand_approval_signature", None)
		for role, output_key in (("first_frame", "reference_image"), ("last_frame", "last_frame_image")):
			row = next((r for r in input_rows if frappe.scrub(r.reference_role or "") == role), None)
			if row:
				shot[output_key] = _get_asset_version_file_url(row.asset_version)
				project_reference = next(
					(
						selection
						for selection in specification.selected_media or []
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
				"reference_key": getattr(project_references.get(row.asset_version), "reference_key", None)
				or "",
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
		fields=[
			"shot",
			"status",
			"progress",
			"error_summary",
			"segment_frame_count",
			"segment_index",
			"pipeline_step_key",
		],
		order_by="creation asc",
	)
	groups = {}
	for job in jobs:
		groups.setdefault(job.shot, []).append(job)
	result = []
	for shot_name, shot_jobs in groups.items():
		shot = frappe.db.get_value(
			"Shot",
			shot_name,
			["shot_number", "shot_name", "selected_output_asset_version"],
			as_dict=True,
		)
		statuses = [row.status for row in shot_jobs]
		# Keep the technical state truthful at the shot boundary.  The client must
		# not turn every unfinished pipeline stage into "Generating": a downstream task
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
			progress = (
				sum(float(row.progress or 0) * max(int(row.segment_frame_count or 0), 0) for row in shot_jobs)
				/ total_frames
			)
		else:
			progress = sum(float(row.progress or 0) for row in shot_jobs) / max(len(shot_jobs), 1)
		active_job = next(
			(row for row in shot_jobs if row.status in ("Running", "Queued", "Ready")),
			next((row for row in shot_jobs if row.status == "Failed"), None),
		)
		output = shot.selected_output_asset_version if shot else None
		result.append(
			{
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
			}
		)
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
