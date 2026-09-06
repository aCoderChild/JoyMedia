# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ShotSpecification(Document):
	def validate(self):
		self.validate_required_workflow_input_mappings()
		self.validate_selected_output_asset_version()

	def validate_selected_output_asset_version(self):
		if not self.selected_output_asset_version:
			return

		generation_jobs = frappe.get_all(
			"Generation Attempt",
			filters={
				"output_asset_version": self.selected_output_asset_version,
				"status": "Completed",
			},
			pluck="generation_job",
		)
		if not generation_jobs or not frappe.db.exists(
			"Generation Job",
			{"name": ["in", generation_jobs], "shot_specification": self.name},
		):
			frappe.throw(
				"Selected Output Asset Version must be a completed Generation Attempt output for this Shot."
			)

	def validate_required_workflow_input_mappings(self):
		workflow_versions = {
			job.workflow_version
			for job in frappe.get_all(
				"Generation Job",
				filters={"shot_specification": self.name},
				fields=["workflow_version"],
			)
			if job.workflow_version
		}
		if not workflow_versions:
			return

		required_bindings = frappe.get_all(
			"Workflow Binding",
			filters={
				"parent": ["in", workflow_versions],
				"parenttype": "Workflow Version",
				"parentfield": "bindings",
				"value_source": "Generation Input",
				"required": 1,
			},
			fields=["parent", "required_input_role"],
		)

		mapping_counts = {}
		for mapping in self.get("generation_inputs") or []:
			if mapping.input_role:
				input_role = frappe.scrub(mapping.input_role)
				mapping_counts[input_role] = mapping_counts.get(input_role, 0) + 1

		for workflow_version, input_role in {
			(binding.parent, binding.required_input_role)
			for binding in required_bindings
			if binding.required_input_role
		}:
			input_role = frappe.scrub(input_role)
			mapping_count = mapping_counts.get(input_role, 0)
			if mapping_count != 1:
				frappe.throw(
					f"Workflow Version {workflow_version} requires exactly one {input_role} mapping; found {mapping_count}."
				)
