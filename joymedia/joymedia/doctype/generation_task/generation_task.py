# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationTask(Document):
	EXECUTION_IMMUTABLE_FIELDS = (
		"generation_run",
		"shot",
		"workflow",
		"prompt_text",
		"prompt_hash",
		"segment_index",
		"segment_frame_count",
		"depends_on_task",
	)

	def validate(self):
		workflow = self._validate_execution_references()
		self._validate_segment_frame_count(workflow)
		self._validate_execution_immutability()
		self._validate_input_immutability()
		if self.status != "Draft":
			self._validate_generation_input_snapshot(workflow)

	def validate_for_execution(self):
		self.validate()
		if self.status not in ("Ready", "Queued"):
			frappe.throw(_("Generation Task {0} must be Ready or Queued for execution.").format(self.name))

	def _validate_segment_frame_count(self, workflow):
		if (
			not self.segment_frame_count
			or self.segment_frame_count < 1
			or self.segment_frame_count > workflow.frame_count
		):
			frappe.throw(
				_("Segment Frame Count must be between 1 and {0} for Workflow {1}.").format(
					workflow.frame_count, workflow.name
				)
			)

	def _validate_execution_references(self):
		if not self.shot or not frappe.db.exists("Shot", self.shot):
			frappe.throw(_("Generation Task requires an existing Shot."))
		if not self.workflow or not frappe.db.exists("Generation Workflow", self.workflow):
			frappe.throw(_("Generation Task requires an existing Generation Workflow."))
		if not self.prompt_text:
			frappe.throw(_("Generation Task requires a prompt text snapshot."))
		if not self.prompt_hash:
			frappe.throw(_("Generation Task requires a prompt hash."))

		shot = frappe.get_doc("Shot", self.shot)
		if not shot.media_project:
			frappe.throw(_("Shot requires a Media Project."))
		project = frappe.get_doc("Media Project", shot.media_project)
		workflow = self._validate_generation_run(project)
		if self.depends_on_task:
			# A dependency means runtime continuation from the upstream task's
			# Last Frame Artifact. Workflows without a first_frame input cannot
			# safely chain long-shot segments or cross-shot continuity.
			from joymedia.services.workflow_resolver import workflow_supports_continuation

			if not workflow_supports_continuation(workflow):
				frappe.throw(
					_(
						"Workflow {0} does not support first-frame continuation, so Generation Task {1} "
						"cannot depend on another task. Shorten the Shot to one workflow segment or use a "
						"continuation-capable workflow."
					).format(workflow.name, self.name or "new task")
				)
			dependency = frappe.get_doc("Generation Task", self.depends_on_task)
			if dependency.generation_run != self.generation_run:
				run = frappe.get_doc("Generation Run", self.generation_run)
				try:
					scope = frappe.parse_json(run.execution_scope_json or "{}")
				except (TypeError, ValueError):
					scope = {}
				if not (
					isinstance(scope, dict)
					and scope.get("continuity")
					and scope.get("continuation_from_task") == dependency.name
				):
					frappe.throw(_("A chained Generation Task dependency must belong to the same Generation Run."))
			if dependency.name == self.name:
				frappe.throw(_("A Generation Task cannot depend on itself."))
		duplicate = frappe.db.exists(
			"Generation Task",
			{
				"generation_run": self.generation_run,
				"shot": self.shot,
				"segment_index": self.segment_index,
				"name": ["!=", self.name],
			},
		)
		if duplicate:
			frappe.throw(_("Only one Generation Task may exist for each shot segment in a run."))
		return workflow

	def _validate_generation_run(self, project):
		if not self.generation_run:
			frappe.throw(_("Generation Task requires a Generation Run."))
		run = frappe.get_doc("Generation Run", self.generation_run)
		if run.media_project != project.name:
			frappe.throw(_("Generation Run Media Project must match the Generation Task Shot."))
		workflow = frappe.get_doc("Generation Workflow", self.workflow)
		try:
			snapshot = frappe.parse_json(run.project_snapshot_json or "{}")
		except (TypeError, ValueError):
			snapshot = {}
		if not isinstance(snapshot, dict):
			snapshot = {}
		shot_snapshot = next(
			(row for row in snapshot.get("shots") or [] if row.get("shot") == self.shot),
			None,
		)
		if shot_snapshot:
			from joymedia.services.workflow_profiles import allowed_workflows_for_shot

			allowed_workflows = allowed_workflows_for_shot(snapshot, shot_snapshot)
			if workflow.name not in {candidate.name for candidate in allowed_workflows}:
				frappe.throw(
					_("Generation Task Workflow {0} is not valid for Shot {1} in this run.").format(
						workflow.name, self.shot
					)
				)
			return workflow
		if run.workflow != self.workflow and frappe.db.get_value(
			"Generation Workflow", run.workflow, "continuation_workflow"
		) != self.workflow:
			frappe.throw(_("Generation Run Workflow must match the Generation Task Workflow."))
		return workflow

	def get_shot_input_snapshot(self):
		shot = frappe.get_doc("Shot", self.shot)
		snapshot = {}
		for mapping in shot.get("generation_inputs") or []:
			input_role = frappe.scrub(mapping.reference_role or "")
			if not input_role or not mapping.asset_version:
				frappe.throw(_("Shot Reference requires an Input Role and Asset Version."))
			snapshot.setdefault(input_role, []).append(mapping.asset_version)
		return snapshot

	def get_generation_input_snapshot(self):
		"""Return the Job-owned frozen input map, preserving repeated role order."""
		snapshot = {}
		for row in self.get("inputs") or []:
			input_role = frappe.scrub(row.input_role or "")
			if not input_role:
				frappe.throw(_("Generation Input requires an Input Role."))
			if bool(row.asset_version) == bool(row.generation_artifact):
				frappe.throw(_("Generation Input must reference exactly one Asset Version or Generation Artifact."))
			snapshot.setdefault(input_role, []).append(row.asset_version or row.generation_artifact)
		return snapshot

	def _validate_generation_input_snapshot(self, workflow):
		actual_snapshot = self.get_generation_input_snapshot()
		# Continuous first_frame is runtime lineage resolved from the dependency per Attempt.
		if self.depends_on_task:
			actual_snapshot.pop("first_frame", None)
			if str(getattr(workflow, "adapter_key", "")).startswith("minimax_h3_sato"):
				actual_snapshot.pop("seed_video", None)
				actual_snapshot.pop("continuation_state", None)

		required_roles = {
			frappe.scrub(binding.required_input_role)
			for binding in workflow.bindings
			if binding.required
			and binding.required_input_role
		}
		for role in required_roles:
			if self.depends_on_task and role == "first_frame":
				continue
			if self.depends_on_task and str(getattr(workflow, "adapter_key", "")).startswith("minimax_h3_sato") and role in {
				"seed_video",
				"continuation_state",
			}:
				continue
			asset_versions = actual_snapshot.get(role, [])
			if not asset_versions or any(
				not frappe.db.get_value("Asset Version", asset_version, "file")
				for asset_version in asset_versions
			):
				frappe.throw(
					_("Generation Task {0} requires usable input(s) with role '{1}'.").format(self.name, role)
				)
			binding = next(
				(binding for binding in workflow.bindings
				 if binding.required and frappe.scrub(binding.required_input_role or "") == role),
				None,
			)
			accepted_media_type = getattr(binding, "accepted_media_type", None) if binding else None
			if binding and accepted_media_type not in (None, "", "Any"):
				for row in self.inputs:
					if frappe.scrub(row.input_role or "") != role or not row.asset_version:
						continue
					media_asset = frappe.db.get_value("Asset Version", row.asset_version, "media_asset")
					media_type = frappe.db.get_value("Media Asset", media_asset, "media_type")
					if media_type != binding.accepted_media_type:
						frappe.throw(
							_("Workflow input role '{0}' accepts {1} media, not {2}.").format(
								role, accepted_media_type, media_type or "unknown"
							)
						)
			from joymedia.services.workflow_resolver import validate_role_input_count

			validate_role_input_count(workflow, role, len(asset_versions))

	def _validate_execution_immutability(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		prepared = previous.status != "Draft" or frappe.db.exists(
			"Generation Attempt", {"generation_task": self.name}
		)
		if not prepared:
			return
		changed_fields = [
			fieldname
			for fieldname in self.EXECUTION_IMMUTABLE_FIELDS
			if getattr(self, fieldname, None) != getattr(previous, fieldname, None)
		]
		if changed_fields:
			frappe.throw(
				_("Generation Task execution fields are immutable after preparation: {0}.").format(
					", ".join(changed_fields)
				)
			)

	def _validate_input_immutability(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		prepared = previous.status != "Draft" or frappe.db.exists(
			"Generation Attempt", {"generation_task": self.name}
		)
		if not prepared:
			return
		if self._normalized_inputs(self.get("inputs")) != self._normalized_inputs(previous.get("inputs")):
			frappe.throw(_("Generation Task inputs are immutable after preparation."))

	@staticmethod
	def _normalized_inputs(rows):
		return [
			(
				frappe.scrub(row.input_role or ""),
				row.asset_version or "",
				row.generation_artifact or "",
			)
			for row in (rows or [])
		]
