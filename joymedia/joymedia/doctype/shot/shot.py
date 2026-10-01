# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Shot(Document):
	def validate(self):
		self._validate_active_run_changes()
		self.validate_required_workflow_input_mappings()
		self.validate_selected_output_asset_version()

	def on_trash(self):
		if frappe.db.exists(
			"Generation Run", {"media_project": self.media_project, "status": ["in", ["Queued", "Running"]]}
		):
			frappe.throw("Shots cannot be deleted while a Generation Run is active.")

	def _validate_active_run_changes(self):
		if self.is_new() or not self.media_project or not frappe.db.exists("Media Project", self.media_project):
			return
		if not frappe.db.exists(
			"Generation Run", {"media_project": self.media_project, "status": ["in", ["Queued", "Running"]]}
		):
			return
		fields = ("shot_number", "duration_seconds", "planned_frame_count", "generation_prompt", "generation_inputs")
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
		from joymedia.services.shot_duration_planner import recalculate_shot_durations

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
				"Selected Output Asset Version must belong to a project output "
				"for this Media Project."
			)

	def validate_required_workflow_input_mappings(self):
		workflow_versions = {
			job.workflow
			for job in frappe.get_all(
				"Generation Task",
				filters={"shot": self.name},
				fields=["workflow"],
			)
			if job.workflow
		}
		if not workflow_versions:
			return

		required_bindings = frappe.get_all(
			"Workflow Binding",
			filters={
				"parent": ["in", workflow_versions],
				"parenttype": "Generation Workflow",
				"parentfield": "bindings",
				"required": 1,
				"binding_key": ["in", ["first_frame", "last_frame"]],
			},
			fields=["parent", "required_input_role"],
		)

		mapping_counts = {}
		for mapping in self.get("generation_inputs") or []:
			if mapping.reference_role:
				input_role = frappe.scrub(mapping.reference_role)
				mapping_counts[input_role] = mapping_counts.get(input_role, 0) + 1

		for workflow, input_role in {
			(binding.parent, binding.required_input_role)
			for binding in required_bindings
			if binding.required_input_role
		}:
			input_role = frappe.scrub(input_role)
			mapping_count = mapping_counts.get(input_role, 0)
			if mapping_count != 1:
				frappe.throw(
					f"Workflow {workflow} requires exactly one {input_role} mapping; found {mapping_count}."
				)
