# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import json
import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.synchronization import filelock

from joymedia.services.project_context import (
	build_project_snapshot,
	_active_project_shots,
	_customer_style_details,
	_get_continuation_workflow,
	_get_customer_workflow_for_export_quality,
	_get_latest_project_generation_run,
	_get_project_reference_contexts,
	_get_project_selected_assets,
	_meaningful_project_value,
	_normalize_generation_mode,
	_plan_append_scene_frames,
	_planning_shot_count,
	_project_settings,
	normalize_export_quality,
	_story_film_planning_context,
)

ALLOWED_STATUSES = {"Draft", "Generating", "Completed", "Needs Attention", "Cancelled", "Archived"}


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
			"workflow", "generation_pipeline", "reference_mode", "quality_mode", "generation_mode", "delivery_preset", "delivery_width",
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
			"show_captions": int(settings.show_captions or 0),
			"soundtrack_prompt": settings.soundtrack_prompt or "",
			"export_quality": normalize_export_quality(settings.export_quality),
			**_customer_style_details(settings),
		}

	@frappe.whitelist()
	def save_video_settings(
		self, total_duration_seconds, delivery_preset,
		generation_mode=None, global_instructions=None, reference_mode=None,
		quality_mode=None, soundtrack_prompt=None,
		export_quality=None, show_captions=None, workflow=None, generation_pipeline=None,
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
		generation_mode = _normalize_generation_mode(generation_mode or self.generation_mode or "Continuous")
		if generation_mode not in ("Multi-shot", "Continuous"):
			frappe.throw(_("Select Continuous or Multi-shot generation mode."))
		reference_mode = reference_mode or getattr(self, "reference_mode", None) or "Single Image"
		if reference_mode not in ("Single Image", "Multi-reference"):
			frappe.throw(_("Select Single Image or Multi-reference."))
		quality_mode = quality_mode or getattr(self, "quality_mode", None) or "Production"
		if quality_mode not in ("Draft", "Production"):
			frappe.throw(_("Select Draft or Production quality."))
		# Workflow and pipeline are selected by the backend from the delivery tier.
		# Keep legacy arguments in the RPC signature but never accept client-side
		# technical execution choices.
		export_quality = normalize_export_quality(export_quality or self.export_quality)
		workflow = _get_customer_workflow_for_export_quality(export_quality)
		from joymedia.services.generation_pipeline_service import pipeline_for_final_workflow
		pipeline = pipeline_for_final_workflow(workflow.name)
		pipeline_name = pipeline.name if pipeline else ""
		self.total_duration_seconds = total_duration_seconds
		self.delivery_preset = delivery_preset
		self.generation_mode = generation_mode
		self.reference_mode = reference_mode
		self.quality_mode = quality_mode
		if global_instructions is not None:
			self.global_instructions = global_instructions
		if show_captions is not None:
			self.show_captions = 1 if str(show_captions).lower() in ("1", "true", "yes", "on") else 0
		if soundtrack_prompt is not None:
			self.soundtrack_prompt = str(soundtrack_prompt).strip()
		self.export_quality = export_quality
		self.workflow = workflow.name
		self.generation_pipeline = pipeline_name
		# Studio finishing turns the 1080p source into a 1440p/60fps delivery.
		# The source remains at the workflow-friendly size; only the customer
		# facing tier determines the final delivery profile.
		studio_source = export_quality == "Studio 1440p60"
		if delivery_preset == "Landscape":
			self.delivery_width, self.delivery_height = (1920, 1080) if studio_source else (1280, 720)
		elif delivery_preset == "Portrait":
			self.delivery_width, self.delivery_height = (1080, 1920) if studio_source else (720, 1280)
		elif delivery_preset == "Square":
			self.delivery_width, self.delivery_height = (1080, 1080) if studio_source else (720, 720)
		if self.status != "Archived":
			latest_run = _get_latest_project_generation_run(self.name)
			self.status = {
				"Queued": "Generating", "Running": "Generating", "Completed": "Completed",
				"Failed": "Needs Attention", "Cancelled": "Cancelled",
			}.get(latest_run.status if latest_run else None, "Draft")
		self.save(ignore_permissions=True)
		frappe.db.commit()
		return self.get_video_settings()

	def _get_project_image_inputs(self):
		from joymedia.services.project_image_manifest import get_project_image_manifest
		return get_project_image_manifest(self.name, include_data_url=True)

	def _use_reference_video_for_story_film(self):
		"""Character + location projects need Reference-to-Video to keep identity and places."""
		from joymedia.services.film_director import is_story_film
		from joymedia.services.vision_analysis import ensure_project_image_analysis

		if getattr(self, "reference_mode", None) == "Multi-reference":
			return
		ensure_project_image_analysis(self)
		if not is_story_film(_get_project_reference_contexts(self)):
			return
		self.save_video_settings(
			self.total_duration_seconds,
			self.delivery_preset,
			generation_mode=self.generation_mode,
			reference_mode="Multi-reference",
			# Keep the project's speed: fast draft or final quality.
			quality_mode=self.quality_mode or "Production",
		)

	def _plan_video(self, *, workflow, video_idea, story_film, shot_count=None,
		reference_images=None, reference_media=None):
		"""Single entry point to the AI Director; shared by first-plan and revision."""
		from joymedia.services.qwen_client import generate_video_plan
		from joymedia.services.workflow_profiles import planning_input_contract
		settings = _project_settings(self)
		return generate_video_plan(
			product_name=_meaningful_project_value(self.product_name, "The supplied product"),
			video_idea=video_idea,
			total_video_duration=float(settings.total_duration_seconds or 15),
			target_fps=workflow.output_fps,
			shot_count=shot_count,
			story_film=story_film,
			reference_images=reference_images,
			reference_media=reference_media,
			generation_mode=_normalize_generation_mode(settings.generation_mode),
			global_instructions=settings.global_instructions,
			format_preset=settings.delivery_preset,
			workflow_input_contract=planning_input_contract(workflow, settings.generation_pipeline),
		)

	def generate_video_plan(self):
		self._require_read_access()
		from joymedia.services.vision_analysis import ensure_project_image_analysis

		# Pictures added or analysed with an older prompt are (re)described first.
		ensure_project_image_analysis(self)
		frappe.db.commit()
		settings = _project_settings(self)
		if not settings.workflow:
			frappe.throw(_("Configure Video Settings before generating a storyboard."))
		image_inputs = self._get_project_image_inputs()
		if not image_inputs:
			frappe.throw(_("Add at least one image reference before creating a storyboard."))
		workflow = frappe.get_doc("Generation Workflow", settings.workflow)
		reference_contexts, story_film = _story_film_planning_context(self)
		return self._plan_video(
			workflow=workflow,
			video_idea=_meaningful_project_value(self.video_idea, "Create a premium cinematic product showcase."),
			story_film=story_film,
			shot_count=(
				None if story_film
				else len(image_inputs)
				if settings.generation_mode == "Multi-shot"
				else _planning_shot_count(settings.total_duration_seconds)
			),
			reference_images=image_inputs,
			reference_media=reference_contexts,
		)

	@frappe.whitelist()
	def revise_storyboard(self, instruction):
		self._require_write_access()
		instruction = (instruction or "").strip()
		if not instruction:
			frappe.throw(_("Describe how the storyboard should change."))
		from joymedia.services.shot_duration_planner import ensure_shot_planning_editable
		from joymedia.services.video_plan_service import apply_video_plan
		ensure_shot_planning_editable(self.name)
		workflow = frappe.get_doc("Generation Workflow", self.workflow)
		current_shots = "\n".join(
			f"Scene {shot.shot_number}: {shot.generation_prompt} ({shot.duration_seconds}s)"
			for shot in _active_project_shots(
				self.name, fields=["shot_number", "generation_prompt", "duration_seconds"]
			)
		)
		reference_contexts, story_film = _story_film_planning_context(self)
		plan = self._plan_video(
			workflow=workflow,
			video_idea=(
				f"{self.video_idea or ''}\n\nCURRENT STORYBOARD:\n{current_shots}"
				f"\n\nREVISION REQUEST:\n{instruction}"
			),
			story_film=story_film,
			reference_media=reference_contexts if story_film else _get_project_selected_assets(self),
		)
		created = apply_video_plan(self.name, plan)
		return {"media_project": self.name, "shots": created}

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
			# Planning takes minutes: longer than a web request may run.
			from joymedia.services.storyboard_job import queue_storyboard

			return queue_storyboard(self.name)
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
				"generation_pipeline": settings.generation_pipeline or None,
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
		from joymedia.services.generation_pipeline_service import get_pipeline_steps, pipeline_for_final_workflow
		from joymedia.joymedia.doctype.generation_attempt.generation_attempt import get_effective_attempt
		from joymedia.services.workflow_profiles import planning_input_contract
		settings = _project_settings(self)

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
				generation_mode="Continuous" if continuity else self.generation_mode,
				global_instructions=self.global_instructions,
				format_preset=self.delivery_preset,
				workflow_input_contract=planning_input_contract(
					workflow,
					settings.generation_pipeline if settings.workflow == workflow.name else None,
				),
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
			compatible_pipeline = self.generation_pipeline or None
			if compatible_pipeline and get_pipeline_steps(compatible_pipeline)[-1].workflow != self.workflow:
				compatible_pipeline = None
			if not compatible_pipeline:
				pipeline = pipeline_for_final_workflow(self.workflow)
				compatible_pipeline = pipeline.name if pipeline else None
			run = frappe.get_doc(
				{
					"doctype": "Generation Run",
					"media_project": self.name,
					"project_snapshot_json": project_snapshot_json,
					"project_snapshot_hash": project_snapshot_hash,
					"execution_scope_json": json.dumps(scope, sort_keys=True),
					"workflow": self.workflow,
					# A continuation profile may not have a compatible keyframe pipeline.
					# Resolve that relationship from registered metadata rather than a
					# Flux/H3 name check.
					"generation_pipeline": compatible_pipeline,
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
			"Generation Run", {"media_project": self.name},
			"name", order_by="creation desc",
		)
		if not run_name or frappe.db.get_value("Generation Run", run_name, "status") != "Failed":
			frappe.throw(_("This project has no failed video run to retry."))
		return retry_failed_jobs_internal(run_name)

	@frappe.whitelist()
	def create_storyboard_revision(self, use_current_workflow_defaults=False):
		self._require_write_access()
		if not self.workflow:
			frappe.throw(_("Configure Video Settings before revising the storyboard."))
		frappe.db.set_value("Media Project", self.name, "status", "Draft", update_modified=False)
		frappe.db.commit()
		return {"media_project": self.name, "version_number": None}
