# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import json
import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.synchronization import filelock

from joymedia.services.project.context import (
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
	_story_film_planning_context,
	build_project_snapshot,
	normalize_export_quality,
)
from joymedia.services.project.formats import ratio_label

ALLOWED_STATUSES = {"Draft", "Generating", "Completed", "Needs Attention", "Cancelled", "Archived"}


class MediaProject(Document):
	def _require_read_access(self):
		self._require_owner_access()
		self.check_permission("read")

	def _require_write_access(self, allow_archived=False):
		self._require_owner_access()
		self.check_permission("write")
		parent_archived = (
			self.get("version_of")
			and frappe.db.get_value("Media Project", self.version_of, "status") == "Archived"
		)
		if not allow_archived and (self.status == "Archived" or parent_archived):
			frappe.throw(_("Restore the project before editing or generating new media."))

	def _require_video_idea(self):
		if not str(self.video_idea or "").strip():
			frappe.throw(_("Enter a non-empty video idea before creating or rendering a storyboard."))

	def _require_owner_access(self):
		from joymedia.services.partners import is_reviewer, require_generation

		if is_reviewer():
			require_generation(self)
		if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles():
			return
		if self.owner != frappe.session.user:
			frappe.throw(_("You do not have access to this project."), frappe.PermissionError)

	def before_insert(self):
		self.status = "Draft"

	def validate(self):
		from joymedia.services.partners import validate_project
		from joymedia.services.project.versions import validate_membership

		validate_project(self)
		validate_membership(self)
		self._validate_generation_affecting_changes()
		self._invalidate_storyboard_approval_for_creative_changes()
		from joymedia.joymedia.doctype.project_reference.project_reference import (
			assign_reference_key,
			assign_reference_role,
			assign_relative_size,
		)

		for reference in self.selected_media or []:
			assign_reference_role(reference)
			assign_relative_size(reference)
			assign_reference_key(reference, self)
		self.project_name = (self.project_name or "").strip()
		self.product_name = (self.product_name or "").strip()
		if not self.project_name:
			frappe.throw(_("Project Name is required."))
		if self.status not in ALLOWED_STATUSES:
			frappe.throw(_("Invalid Media Project status."))

	def _invalidate_storyboard_approval_for_creative_changes(self):
		"""A reviewed storyboard is only valid for the creative brief it reviewed."""
		if self.is_new() or self.storyboard_approval_status != "Approved":
			return
		previous = frappe.db.get_value(
			"Media Project",
			self.name,
			[
				"video_idea",
				"product_name",
				"global_instructions",
				"delivery_preset",
				"delivery_width",
				"delivery_height",
			],
			as_dict=True,
		)
		if previous and any(self.get(fieldname) != previous.get(fieldname) for fieldname in previous):
			self.storyboard_approval_status = "Ready for Review"
			return
		# Adding material to the project library does not alter an approved shot.
		# Removing or re-roling an image already assigned to a Shot does, so make
		# that dependency explicit instead of invalidating every library edit.
		previous_doc = self.get_doc_before_save()
		if not previous_doc:
			return
		previous_roles = {
			row.asset_version: row.reference_role or "General"
			for row in previous_doc.selected_media or []
			if row.asset_version
		}
		current_roles = {
			row.asset_version: row.reference_role or "General"
			for row in self.selected_media or []
			if row.asset_version
		}
		shot_names = frappe.get_all(
			"Shot", filters={"media_project": self.name, "is_removed": 0}, pluck="name"
		)
		used_versions = (
			set(
				frappe.get_all(
					"Shot Reference",
					filters={"parenttype": "Shot", "parent": ["in", shot_names]},
					pluck="asset_version",
				)
			)
			if shot_names
			else set()
		)
		if any(current_roles.get(version) != previous_roles.get(version) for version in used_versions):
			self.storyboard_approval_status = "Ready for Review"

	def _validate_generation_affecting_changes(self):
		if self.is_new() or not frappe.db.exists("Media Project", self.name):
			return
		if not frappe.db.exists(
			"Generation Run", {"media_project": self.name, "status": ["in", ["Queued", "Running"]]}
		):
			return
		fields = (
			"workflow",
			"generation_pipeline",
			"reference_mode",
			"quality_mode",
			"generation_mode",
			"delivery_preset",
			"delivery_width",
			"delivery_height",
			"total_duration_seconds",
			"global_instructions",
			"selected_media",
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
				_(
					"Generation-affecting project settings are read-only while a Generation Run is active. "
					"Stop the active run or create a new revision first."
				)
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
			"delivery_width": settings.delivery_width,
			"delivery_height": settings.delivery_height,
			"generation_mode": _normalize_generation_mode(settings.generation_mode),
			"global_instructions": settings.global_instructions or "",
			"show_captions": int(settings.show_captions or 0),
			"soundtrack_prompt": settings.soundtrack_prompt or "",
			"export_quality": normalize_export_quality(settings.export_quality),
			"character_mode": self.character_mode or "Draw in scene",
			"soundtrack_mode": self.soundtrack_mode or "Sound effects only",
			"planning_mode": self.planning_mode or "Creative",
			**_customer_style_details(settings),
		}

	@frappe.whitelist()
	def save_video_settings(
		self,
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
		aspect_ratio=None,
	):
		self._require_write_access()
		try:
			total_duration_seconds = float(total_duration_seconds)
		except (TypeError, ValueError):
			frappe.throw(_("Duration must be greater than zero."))
		if not math.isfinite(total_duration_seconds) or not 1 <= total_duration_seconds <= 60:
			frappe.throw(_("Duration must be between 1 and 60 seconds."))
		if aspect_ratio:
			from joymedia.services.project.formats import orientation, parse_ratio

			try:
				ratio = parse_ratio(aspect_ratio)
				if not ratio:
					raise ValueError("Specify an aspect ratio such as 16:9 or 4:5.")
				delivery_preset = orientation(ratio)
			except ValueError as exc:
				frappe.throw(_(str(exc)))
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
		from joymedia.services.workflows.pipeline import (
			get_pinned_generation_pipeline,
			pipeline_for_final_workflow,
		)

		pipeline = get_pinned_generation_pipeline(self.name)
		if pipeline:
			workflow = frappe.get_doc("Generation Workflow", pipeline.steps[-1].workflow)
		else:
			workflow = _get_customer_workflow_for_export_quality(export_quality)
			pipeline = pipeline_for_final_workflow(workflow.name)
		pipeline_name = pipeline.name if pipeline else ""
		previous_preset = self.delivery_preset
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
		for fieldname, value, allowed in (
			("character_mode", character_mode, ("Draw in scene", "Paste exact art")),
			(
				"soundtrack_mode",
				soundtrack_mode,
				("Full soundtrack", "Sound effects only", "Effects + music", "Separate effects layer"),
			),
			("planning_mode", planning_mode, ("Creative", "Follow the sheet")),
		):
			if value in (None, ""):
				continue
			if value not in allowed:
				frappe.throw(
					_("{0} must be one of: {1}.").format(self.meta.get_label(fieldname), ", ".join(allowed))
				)
			setattr(self, fieldname, value)
		self.export_quality = export_quality
		self.workflow = workflow.name
		self.generation_pipeline = pipeline_name
		from joymedia.services.project.formats import (
			PRESET_RATIOS,
			delivery_dimensions,
			orientation,
			parse_ratio,
		)

		try:
			ratio = parse_ratio(aspect_ratio) if aspect_ratio else None
			if aspect_ratio and not ratio:
				raise ValueError("Specify an aspect ratio such as 16:9 or 4:5.")
			if (
				ratio is None
				and self.delivery_width
				and self.delivery_height
				and delivery_preset == previous_preset
			):
				ratio = parse_ratio(f"{self.delivery_width}:{self.delivery_height}")
			ratio = ratio or PRESET_RATIOS[delivery_preset]
			self.delivery_preset = orientation(ratio)
			self.delivery_width, self.delivery_height = delivery_dimensions(
				ratio, 1080 if export_quality == "Studio 1440p60" else 720
			)
		except ValueError as exc:
			frappe.throw(_(str(exc)))
		if self.status != "Archived":
			latest_run = _get_latest_project_generation_run(self.name)
			self.status = {
				"Queued": "Generating",
				"Running": "Generating",
				"Completed": "Completed",
				"Failed": "Needs Attention",
				"Cancelled": "Cancelled",
			}.get(latest_run.status if latest_run else None, "Draft")
		self.save(ignore_permissions=True)
		frappe.db.commit()
		return self.get_video_settings()

	def _get_project_image_inputs(self):
		from joymedia.services.intake.image_manifest import get_project_image_manifest

		return get_project_image_manifest(self.name, include_data_url=True)

	def _use_reference_video_for_story_film(self):
		"""Character + location projects need Reference-to-Video to keep identity and places."""
		from joymedia.services.intake.vision import ensure_project_image_analysis
		from joymedia.services.planning.film_director import (
			infer_product_reference_contexts,
			is_story_film,
		)

		if getattr(self, "reference_mode", None) == "Multi-reference":
			return
		ensure_project_image_analysis(self)
		references = _get_project_reference_contexts(self)
		references = infer_product_reference_contexts(references, self.video_idea)
		# Rendering routes use the durable Project Reference role, rather than the
		# planner-only context. Persist an inferred role so a reference cannot fall back to General.
		inferred_roles = {
			str(item.get("reference_key") or ""): item.get("reference_role") for item in references
		}
		for selected in self.selected_media or []:
			role = inferred_roles.get(str(selected.reference_key or ""))
			if role and selected.reference_role != role:
				frappe.db.set_value(
					"Project Reference", selected.name, "reference_role", role, update_modified=False
				)
				selected.reference_role = role
		if not is_story_film(references):
			return
		self.save_video_settings(
			self.total_duration_seconds,
			self.delivery_preset,
			generation_mode=self.generation_mode,
			reference_mode="Multi-reference",
			# Keep the project's speed: fast draft or final quality.
			quality_mode=self.quality_mode or "Production",
		)

	def _plan_video(
		self,
		*,
		workflow,
		video_idea,
		story_film,
		shot_count=None,
		reference_images=None,
		reference_media=None,
	):
		"""Single entry point to the AI Director; shared by first-plan and revision."""
		from joymedia.services.planning.llm import generate_video_plan
		from joymedia.services.workflows.routing import automatic_planning_input_contract

		settings = _project_settings(self)
		return generate_video_plan(
			product_name=_meaningful_project_value(self.product_name, "The supplied product"),
			video_idea=video_idea,
			total_video_duration=float(settings.total_duration_seconds or 0),
			target_fps=workflow.output_fps,
			shot_count=shot_count,
			story_film=story_film,
			reference_images=reference_images,
			reference_media=reference_media,
			generation_mode=_normalize_generation_mode(settings.generation_mode),
			global_instructions=settings.global_instructions,
			format_preset=ratio_label(settings.delivery_width, settings.delivery_height),
			workflow_input_contract=automatic_planning_input_contract(),
		)

	def generate_video_plan(self):
		self._require_read_access()
		self._require_video_idea()
		from joymedia.services.intake.cinematography import ensure_project_camera_analysis
		from joymedia.services.intake.vision import ensure_project_image_analysis

		ensure_project_camera_analysis(self)
		# Pictures added or analysed with an older prompt are (re)described first.
		ensure_project_image_analysis(self)
		frappe.db.commit()
		settings = _project_settings(self)
		if not settings.workflow:
			frappe.throw(_("Configure Video Settings before generating a storyboard."))
		image_inputs = self._get_project_image_inputs()
		workflow = frappe.get_doc("Generation Workflow", settings.workflow)
		reference_contexts, story_film = _story_film_planning_context(self)
		return self._plan_video(
			workflow=workflow,
			video_idea=self.video_idea.strip(),
			story_film=story_film,
			shot_count=(
				None
				if story_film
				else len(image_inputs) or None
				if settings.generation_mode == "Multi-shot"
				else _planning_shot_count(settings.total_duration_seconds)
			),
			reference_images=image_inputs,
			reference_media=reference_contexts,
		)

	@frappe.whitelist()
	def revise_storyboard(self, instruction):
		self._require_write_access()
		self._refuse_if_sheet()
		instruction = (instruction or "").strip()
		if not instruction:
			frappe.throw(_("Describe how the storyboard should change."))
		from joymedia.services.planning.durations import ensure_shot_planning_editable
		from joymedia.services.planning.video_plan import apply_video_plan

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
		self.storyboard_approval_status = "Ready for Review"
		self.save(ignore_permissions=True)
		return {"media_project": self.name, "shots": created}

	@frappe.whitelist()
	def generate_end_to_end(self):
		self._require_write_access()
		self._require_video_idea()
		if (
			frappe.db.exists("Shot", {"media_project": self.name, "is_removed": 0})
			and self.storyboard_approval_status != "Approved"
		):
			frappe.throw(_("Review and approve the storyboard before starting generation."))
		from joymedia.services.planning.signature import assert_plan_matches_approval

		assert_plan_matches_approval(self)
		if not self.workflow:
			frappe.throw(_("Configure Video Settings before generating a storyboard."))
		current_snapshot_hash = build_project_snapshot(self)[1]
		latest_run = frappe.db.get_value(
			"Generation Run",
			{"media_project": self.name},
			["name", "status"],
			as_dict=True,
			order_by="creation desc",
		)
		if latest_run and latest_run.status in ("Queued", "Running"):
			return {"run": latest_run.name, "status": latest_run.status}
		if latest_run and latest_run.status == "Failed":
			latest_hash = frappe.db.get_value("Generation Run", latest_run.name, "project_snapshot_hash")
			if latest_hash == current_snapshot_hash and frappe.db.exists(
				"Generation Task", {"generation_run": latest_run.name}
			):
				return self.retry_failed_jobs()
		if not frappe.db.exists("Shot", {"media_project": self.name, "is_removed": 0}):
			# Planning takes minutes: longer than a web request may run.
			from joymedia.services.planning.jobs import queue_storyboard

			return queue_storyboard(self.name)
		return self.generate_video()

	def follows_sheet(self):
		"""Whether the storyboard is the advertiser's imported sheet, followed as written: the sheet decides the idea and
		the scenes, so they are changed by editing the sheet and importing it again, not by asking the AI."""
		return bool(self.storyboard_source_file) and self.planning_mode == "Follow the sheet"

	def _refuse_if_sheet(self):
		if self.follows_sheet():
			frappe.throw(
				_(
					"This storyboard follows the imported sheet. Edit the sheet and import it again to change it."
				)
			)

	def follow_active_pipeline(self):
		"""Re-pin the project to the workflow and pipeline the site now uses for its quality tier.

		A project stores the workflow it was last saved with, so promoting a new pipeline would otherwise leave every
		existing project on the old one until someone re-saved its settings.
		"""
		if not self.workflow:
			return
		from joymedia.services.workflows.pipeline import (
			get_pinned_generation_pipeline,
			pipeline_for_final_workflow,
		)

		override = get_pinned_generation_pipeline(self.name)
		if override:
			self.db_set(
				{"workflow": override.steps[-1].workflow, "generation_pipeline": override.name},
				update_modified=False,
			)
			return

		try:
			workflow = _get_customer_workflow_for_export_quality(
				normalize_export_quality(self.export_quality)
			)
			pipeline = pipeline_for_final_workflow(workflow.name)
		except frappe.ValidationError:
			return  # nothing active to move to; the generation preflight reports what is missing
		pinned = {"workflow": workflow.name, "generation_pipeline": pipeline.name if pipeline else ""}
		if any(self.get(key) != value for key, value in pinned.items()):
			self.db_set(pinned, update_modified=False)

	@frappe.whitelist()
	def generate_video(self):
		self._require_write_access()
		self._require_video_idea()
		if self.storyboard_approval_status != "Approved":
			frappe.throw(_("Review and approve the storyboard before starting generation."))
		from joymedia.services.generation.orchestrator import (
			start_run_internal,
			validate_generation_preflight,
		)
		from joymedia.services.planning.durations import recalculate_shot_durations

		with filelock(f"joymedia-generate-video-{self.name}"):
			existing = frappe.db.get_value(
				"Generation Run",
				{"media_project": self.name, "status": ["not in", ["Completed", "Failed", "Cancelled"]]},
				["name", "status"],
				as_dict=True,
			)
			if existing:
				return {"run": existing.name, "status": existing.status}
			if not frappe.db.exists("Shot", {"media_project": self.name, "is_removed": 0}):
				frappe.throw(_("Generate a storyboard first."))
			self.follow_active_pipeline()
			settings = _project_settings(self)
			if not settings.workflow:
				frappe.throw(_("This project has no active Generation Workflow."))
			workflow = frappe.get_doc("Generation Workflow", settings.workflow)
			recalculate_shot_durations(self.name)
			# Duration rebalancing is deterministic for the approved plan, so re-seal it.
			from joymedia.services.planning.signature import compute_plan_signature

			plan_signature = compute_plan_signature(self.name)
			if self.approved_plan_signature:
				self.db_set("approved_plan_signature", plan_signature, update_modified=False)
			shots = _active_project_shots(
				self.name,
				fields=["name", "shot_number", "planned_frame_count"],
			)
			validate_generation_preflight(self, workflow, shots, check_comfyui=True)
			project_snapshot_json, project_snapshot_hash = build_project_snapshot(
				self, require_production_pipeline=True
			)
			snapshot = frappe.parse_json(project_snapshot_json)
			# A whole-video request replaces existing selected takes once its new
			# renders complete. A first render has no selection and remains unchanged.
			replace_selection = any(
				frappe.db.get_value("Shot", shot.name, "selected_output_asset_version") for shot in shots
			)
			run = frappe.get_doc(
				{
					"doctype": "Generation Run",
					"media_project": self.name,
					"project_snapshot_json": project_snapshot_json,
					"project_snapshot_hash": project_snapshot_hash,
					"execution_scope_json": json.dumps(
						{"replace_selection": replace_selection, "plan_signature": plan_signature}
					),
					"workflow": settings.workflow,
					"generation_pipeline": snapshot.get("generation_pipeline") or None,
					"requested_by": frappe.session.user,
					"status": "Draft",
				}
			).insert(ignore_permissions=True)
			result = start_run_internal(run.name, preflight_checked=True)
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

		from joymedia.joymedia.doctype.generation_attempt.generation_attempt import get_effective_attempt
		from joymedia.services.generation.artifacts import get_attempt_artifact
		from joymedia.services.planning.llm import generate_video_plan
		from joymedia.services.planning.video_plan import append_video_plan
		from joymedia.services.workflows.routing import automatic_planning_input_contract

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
				frappe.throw(
					_(
						"The storyboard changed since Add Scene was opened. Please reopen Add Scene and try again."
					)
				)

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
			plan = generate_video_plan(
				product_name=_meaningful_project_value(self.product_name, "The supplied product"),
				video_idea=_meaningful_project_value(
					self.video_idea, "Create a premium cinematic product showcase."
				),
				total_video_duration=duration_seconds,
				target_fps=workflow.output_fps,
				shot_count=len(target_frames),
				reference_images=image_inputs,
				reference_media=_get_project_reference_contexts(self),
				generation_mode="Continuous" if continuity else self.generation_mode,
				global_instructions=self.global_instructions,
				format_preset=ratio_label(self.delivery_width, self.delivery_height),
				workflow_input_contract=automatic_planning_input_contract(),
				continuation_context={
					"previous_prompt": last_shot.generation_prompt,
					"instruction": str(instruction or "").strip(),
				},
			)
			if len(plan.get("shots") or []) != len(target_frames):
				frappe.throw(_("AI Director returned an unexpected number of scenes."))
			fps = float(workflow.output_fps)
			for shot, frame_count in zip(plan["shots"], target_frames, strict=False):
				shot["planned_frame_count"] = int(frame_count)
				shot["duration_seconds"] = frame_count / fps
			new_shot_names = append_video_plan(
				self.name,
				plan,
				start_after_shot_number=int(last_shot.shot_number),
			)
			self.total_duration_seconds = float(self.total_duration_seconds or 0) + duration_seconds
			# Appending is a storyboard change, not permission to spend GPU time.  The
			# editor must explicitly review and re-approve the updated plan.
			self.storyboard_approval_status = "Ready for Review"
			self.save(ignore_permissions=True)
			frappe.db.commit()
			return {"status": "Ready for Review", "shots": new_shot_names}

	@frappe.whitelist()
	def retry_failed_jobs(self):
		self._require_write_access()
		from joymedia.services.generation.orchestrator import retry_failed_jobs_internal

		run_name = frappe.db.get_value(
			"Generation Run",
			{"media_project": self.name},
			"name",
			order_by="creation desc",
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
