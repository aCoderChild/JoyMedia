# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationJob(Document):
	def validate(self):
		workflow_version = self._validate_execution_references()
		self._validate_segment_frame_count(workflow_version)
		self._validate_input_immutability()
		if self.status != "Draft":
			self._validate_generation_input_snapshot(workflow_version)

	def validate_for_execution(self):
		self.validate()
		if self.status not in ("Ready", "Queued"):
			frappe.throw(_("Generation Job {0} must be Ready or Queued for execution.").format(self.name))

	def _validate_segment_frame_count(self, workflow_version):
		if (
			not self.segment_frame_count
			or self.segment_frame_count < 1
			or self.segment_frame_count > workflow_version.frame_count
		):
			frappe.throw(
				_("Segment Frame Count must be between 1 and {0} for Workflow {1}.").format(
					workflow_version.frame_count, workflow_version.name
				)
			)

	def _validate_execution_references(self):
		if not self.shot_specification or not frappe.db.exists("Shot Specification", self.shot_specification):
			frappe.throw(_("Generation Job requires an existing Shot Specification."))
		if not self.workflow_version or not frappe.db.exists("Generation Workflow", self.workflow_version):
			frappe.throw(_("Generation Job requires an existing Generation Workflow."))
		if not self.prompt_text:
			frappe.throw(_("Generation Job requires a prompt text snapshot."))
		if not self.prompt_hash:
			frappe.throw(_("Generation Job requires a prompt hash."))

		shot = frappe.get_doc("Shot Specification", self.shot_specification)
		if not shot.media_project:
			frappe.throw(_("Shot Specification requires a Media Project."))
		project = frappe.get_doc("Media Project", shot.media_project)
		self._validate_generation_run(project)
		if self.workflow_version != project.workflow:
			frappe.throw(_("Generation Job Workflow must match the Media Project Workflow."))
		if self.depends_on_job:
			dependency = frappe.get_doc("Generation Job", self.depends_on_job)
			if dependency.generation_run != self.generation_run:
				frappe.throw(_("A chained Generation Job dependency must belong to the same Generation Run."))
			if dependency.name == self.name:
				frappe.throw(_("A Generation Job cannot depend on itself."))
		duplicate = frappe.db.exists(
			"Generation Job",
			{
				"generation_run": self.generation_run,
				"shot_specification": self.shot_specification,
				"segment_index": self.segment_index,
				"name": ["!=", self.name],
			},
		)
		if duplicate:
			frappe.throw(_("Only one Generation Job may exist for each shot segment in a run."))
		return frappe.get_doc("Generation Workflow", self.workflow_version)

	def _validate_generation_run(self, project):
		if not self.generation_run:
			frappe.throw(_("Generation Job requires a Generation Run."))
		run = frappe.get_doc("Generation Run", self.generation_run)
		if run.media_project != project.name:
			frappe.throw(_("Generation Run Media Project must match the Generation Job Shot Specification."))
		if run.workflow_version != self.workflow_version:
			frappe.throw(_("Generation Run Workflow must match the Generation Job Workflow."))

	def get_shot_input_snapshot(self):
		shot = frappe.get_doc("Shot Specification", self.shot_specification)
		snapshot = {}
		for mapping in shot.get("generation_inputs") or []:
			input_role = frappe.scrub(mapping.input_role or "")
			if not input_role or not mapping.asset_version:
				frappe.throw(_("Shot Input Mapping requires an Input Role and Asset Version."))
			if input_role in snapshot:
				frappe.throw(_("Shot Input Mapping has more than one entry for role '{0}'.").format(input_role))
			snapshot[input_role] = mapping.asset_version
		return snapshot

	def get_generation_input_snapshot(self):
		"""Return the Job-owned frozen input map."""
		snapshot = {}
		for row in self.get("inputs") or []:
			input_role = frappe.scrub(row.input_role or "")
			if not input_role:
				frappe.throw(_("Generation Input requires an Input Role."))
			if bool(row.asset_version) == bool(row.generation_artifact):
				frappe.throw(_("Generation Input must reference exactly one Asset Version or Generation Artifact."))
			if input_role in snapshot:
				frappe.throw(_("Generation Job has more than one input for role '{0}'.").format(input_role))
			snapshot[input_role] = row.asset_version or row.generation_artifact
		return snapshot

	def _validate_generation_input_snapshot(self, workflow_version):
		expected_snapshot = self.get_shot_input_snapshot()
		actual_snapshot = self.get_generation_input_snapshot()
		# Continuous first_frame is runtime lineage resolved from the dependency per Attempt.
		if self.depends_on_job:
			expected_snapshot.pop("first_frame", None)
			actual_snapshot.pop("first_frame", None)
		if actual_snapshot != expected_snapshot:
			frappe.throw(_("Generation Job inputs must exactly match the Shot Input Mapping snapshot."))

		required_roles = {
			frappe.scrub(binding.required_input_role)
			for binding in workflow_version.bindings
			if binding.binding_key in {"first_frame", "last_frame"}
			and binding.required
			and binding.required_input_role
		}
		for role in required_roles:
			if self.depends_on_job and role == "first_frame":
				continue
			asset_version = actual_snapshot.get(role)
			if not asset_version or not frappe.db.get_value("Asset Version", asset_version, "file"):
				frappe.throw(
					_("Generation Job {0} requires one usable input with role '{1}'.").format(self.name, role)
				)

	def _validate_input_immutability(self):
		if self.is_new() or not frappe.db.exists("Generation Attempt", {"generation_job": self.name}):
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		if self._normalized_inputs(self.get("inputs")) != self._normalized_inputs(previous.get("inputs")):
			frappe.throw(_("Generation Job inputs are immutable after execution begins."))

	@staticmethod
	def _normalized_inputs(rows):
		return sorted(
			(
				frappe.scrub(row.input_role or ""),
				row.asset_version or "",
				row.generation_artifact or "",
			)
			for row in (rows or [])
		)
