# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Shot(Document):
	def validate(self):
		self._validate_active_run_changes()
		if not self.is_new():
			# A derived plan cannot survive a source edit unchanged. Preserve an
			# explicitly replaced plan, as when the director saves a fresh draft.
			if self.has_value_changed("generation_prompt") or self.has_value_changed("image_prompt"):
				for field in ("motion_plan_json", "end_state", "handoff_type"):
					if not self.has_value_changed(field) and not (
						field == "motion_plan_json" and self.flags.get("explicit_motion_plan")
					):
						self.set(field, None)
			if self.has_value_changed("image_prompt") and not self.has_value_changed("start_state"):
				self.start_state = None
		from joymedia.services.scene.contract import read_contract

		try:
			read_contract(self.motion_plan_json, self.duration_seconds)
		except ValueError as exc:
			frappe.throw(str(exc))
		self.validate_required_workflow_input_mappings()
		self.validate_selected_output_asset_version()

	def on_trash(self):
		if frappe.db.exists(
			"Generation Run", {"media_project": self.media_project, "status": ["in", ["Queued", "Running"]]}
		):
			frappe.throw("Shots cannot be deleted while a Generation Run is active.")

	def _validate_active_run_changes(self):
		if (
			self.is_new()
			or not self.media_project
			or not frappe.db.exists("Media Project", self.media_project)
		):
			return
		if not frappe.db.exists(
			"Generation Run", {"media_project": self.media_project, "status": ["in", ["Queued", "Running"]]}
		):
			return
		fields = (
			"shot_number",
			"duration_seconds",
			"planned_frame_count",
			"storyboard_action",
			"generation_prompt",
			"image_prompt",
			"motion_plan_json",
			"start_state",
			"end_state",
			"handoff_type",
			"continuity_mode",
			"generation_inputs",
		)
		if any(self.has_value_changed(fieldname) for fieldname in fields):
			frappe.throw("Generation-affecting Shot fields are read-only while a Generation Run is active.")

	def after_insert(self):
		self._recalculate_durations()

	def on_update(self):
		previous = self.get_doc_before_save()
		if previous and previous.media_project != self.media_project:
			self._recalculate_durations(previous.media_project)
			self._recalculate_durations()

	def after_delete(self):
		self._recalculate_durations()

	def _recalculate_durations(self, media_project=None):
		if self.flags.get("preserve_authored_timing"):
			return
		from joymedia.services.planning.durations import recalculate_shot_durations

		recalculate_shot_durations(media_project or self.media_project)

	def validate_selected_output_asset_version(self):
		if not self.selected_output_asset_version:
			return

		asset_version = frappe.get_doc("Asset Version", self.selected_output_asset_version)
		media_asset = frappe.get_doc("Media Asset", asset_version.media_asset)
		project = frappe.get_doc("Media Project", self.media_project)
		if (
			media_asset.media_type != "Video"
			or media_asset.asset_scope != "Project Output"
			or media_asset.media_project != project.name
		):
			frappe.throw(
				"Selected Output Asset Version must belong to a project output for this Media Project."
			)

	def validate_required_workflow_input_mappings(self):
		workflow = frappe.db.get_value("Media Project", self.media_project, "workflow")
		if not workflow:
			return

		required_bindings = frappe.get_all(
			"Workflow Binding",
			filters={
				"parent": workflow,
				"parenttype": "Generation Workflow",
				"parentfield": "bindings",
				"required": 1,
				"binding_key": ["in", ["first_frame", "last_frame"]],
			},
			fields=["parent", "required_input_role", "value_type"],
		)

		mapping_counts = {}
		for mapping in self.get("generation_inputs") or []:
			if mapping.reference_role:
				input_role = frappe.scrub(mapping.reference_role)
				mapping_counts[input_role] = mapping_counts.get(input_role, 0) + 1

		for input_role, value_type in {
			(binding.required_input_role, binding.value_type)
			for binding in required_bindings
			if binding.required_input_role
		}:
			input_role = frappe.scrub(input_role)
			# first_frame/last_frame are execution lineage, not creative Shot
			# inputs. They are frozen on Generation Task/Attempt when the run is
			# prepared and may be resolved from an upstream completed artifact.
			if input_role in {"first_frame", "last_frame"}:
				continue
			mapping_count = mapping_counts.get(input_role, 0)
			if (value_type == "File Paths" and mapping_count < 1) or (
				value_type != "File Paths" and mapping_count != 1
			):
				frappe.throw(
					f"Workflow {workflow} requires "
					f"{'at least one' if value_type == 'File Paths' else 'exactly one'} "
					f"{input_role} mapping; found {mapping_count}."
				)
