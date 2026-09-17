# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationJob(Document):
	def validate(self):
		self._validate_requested_variants()
		workflow_version = self._validate_execution_references()
		if self.status != "Draft":
			self._validate_generation_input_snapshot(workflow_version)

	def validate_for_execution(self):
		self.validate()
		if self.status not in ("Ready", "Queued"):
			frappe.throw(_("Generation Job {0} must be Ready or Queued for execution.").format(self.name))

		workflow_version = frappe.get_doc("Workflow Version", self.workflow_version)
		if workflow_version.status not in ("Testing", "Production"):
			frappe.throw(
				_("Workflow Version {0} must be Testing or Production.").format(workflow_version.name)
			)

	def _validate_requested_variants(self):
		if not self.requested_variants or self.requested_variants < 1:
			frappe.throw(_("Requested Variants must be greater than zero."))

	def _validate_execution_references(self):
		if not self.shot_specification or not frappe.db.exists("Shot Specification", self.shot_specification):
			frappe.throw(_("Generation Job requires an existing Shot Specification."))
		if not self.workflow_version or not frappe.db.exists("Workflow Version", self.workflow_version):
			frappe.throw(_("Generation Job requires an existing Workflow Version."))
		if not self.compiled_prompt or not frappe.db.exists("Compiled Prompt", self.compiled_prompt):
			frappe.throw(_("Generation Job requires an existing Compiled Prompt."))

		shot = frappe.get_doc("Shot Specification", self.shot_specification)
		media_specification = frappe.get_doc("Media Specification", shot.media_specification)
		self._validate_generation_run(media_specification)
		compiled_prompt_shot = frappe.db.get_value(
			"Compiled Prompt", self.compiled_prompt, "shot_specification"
		)
		if compiled_prompt_shot != self.shot_specification:
			frappe.throw(
				_("Generation Job Shot Specification must match the Compiled Prompt Shot Specification.")
			)

		if self.workflow_version != media_specification.generation_workflow_version:
			frappe.throw(_("Generation Job Workflow Version must match the Media Specification Workflow Version."))

		prompt_template_version = frappe.db.get_value(
			"Compiled Prompt", self.compiled_prompt, "prompt_template_version"
		)
		if prompt_template_version != media_specification.prompt_template_version:
			frappe.throw(
				_("Compiled Prompt Template Version must match the Media Specification Prompt Template Version.")
			)

		prompt_template = frappe.db.get_value(
			"Prompt Template Version", prompt_template_version, "prompt_template"
		)
		workflow_profile = frappe.db.get_value(
			"Workflow Version", self.workflow_version, "workflow_profile"
		)
		prompt_profile = frappe.db.get_value("Prompt Template", prompt_template, "workflow_profile")
		if not workflow_profile or not prompt_profile or workflow_profile != prompt_profile:
			frappe.throw(_("Workflow and prompt template profiles must match."))
		return frappe.get_doc("Workflow Version", self.workflow_version)

	def _validate_generation_run(self, media_specification):
		if not self.generation_run:
			return

		run = frappe.get_doc("Generation Run", self.generation_run)
		if run.media_specification != media_specification.name:
			frappe.throw(
				_("Generation Run Media Specification must match the Generation Job Shot Specification.")
			)
		if run.workflow_version != self.workflow_version:
			frappe.throw(_("Generation Run Workflow Version must match the Generation Job Workflow Version."))

	def get_shot_input_snapshot(self):
		shot = frappe.get_doc("Shot Specification", self.shot_specification)
		snapshot = {}
		for mapping in shot.get("generation_inputs") or []:
			input_role = frappe.scrub(mapping.input_role or "")
			if not input_role or not mapping.asset_version:
				frappe.throw(_("Shot Input Mapping requires an Input Role Key and Asset Version."))
			if input_role in snapshot:
				frappe.throw(_("Shot Input Mapping has more than one entry for role '{0}'.").format(input_role))
			snapshot[input_role] = mapping.asset_version
		return snapshot

	def _get_generation_input_snapshot(self):
		snapshot = {}
		for row in frappe.get_all(
			"Generation Input",
			filters={"generation_job": self.name},
			fields=["name", "input_role", "asset_version"],
		):
			input_role = frappe.scrub(row.input_role or "")
			if not input_role or not row.asset_version:
				frappe.throw(_("Generation Input {0} requires an Input Role Key and Asset Version.").format(row.name))
			if input_role in snapshot:
				frappe.throw(_("Generation Job has more than one Generation Input for role '{0}'.").format(input_role))
			snapshot[input_role] = row.asset_version
		return snapshot

	def _validate_generation_input_snapshot(self, workflow_version):
		expected_snapshot = self.get_shot_input_snapshot()
		actual_snapshot = self._get_generation_input_snapshot()
		if actual_snapshot != expected_snapshot:
			frappe.throw(_("Generation Inputs must exactly match the Shot Input Mapping snapshot."))

		required_roles = {
			frappe.scrub(binding.required_input_role)
			for binding in workflow_version.bindings
			if binding.value_source == "Generation Input" and binding.required and binding.required_input_role
		}
		for role in required_roles:
			asset_version = actual_snapshot.get(role)
			if not asset_version or not frappe.db.get_value("Asset Version", asset_version, "file"):
				frappe.throw(
					_("Generation Job {0} requires exactly one usable input with role '{1}'.").format(
						self.name, role
					)
				)
