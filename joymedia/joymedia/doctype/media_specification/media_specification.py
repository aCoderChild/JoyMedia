# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

from typing import ClassVar

import frappe
from frappe import _
from frappe.model.document import Document

from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow


class MediaSpecification(Document):
	IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = ("media_project", "version_number")
	EXECUTION_CONTRACT_FIELDS: ClassVar[tuple[str, ...]] = (
		"workflow",
		"video_style",
		"total_duration_seconds",
		"delivery_preset",
		"delivery_width",
		"delivery_height",
		"continuity_mode",
		"global_instructions",
		"planning_context_json",
		"planning_context_hash",
	)
	PRESET_DIMENSIONS: ClassVar[dict[str, tuple[int, int]]] = {
		"Landscape": (1344, 768),
		"Portrait": (768, 1344),
		"Square": (1024, 1024),
	}
	REVISION_FIELDS: ClassVar[tuple[str, ...]] = (
		"workflow",
		"video_style",
		"continuity_mode",
		"total_duration_seconds",
		"delivery_preset",
		"delivery_width",
		"delivery_height",
		"global_instructions",
	)

	# Temporary compatibility aliases for server code/tests created before the
	# prompt model was simplified. These are not DocType fields.
	@property
	def generation_instructions(self):
		return self.get("global_instructions")

	@generation_instructions.setter
	def generation_instructions(self, value):
		self.set("global_instructions", value)

	@property
	def global_consistency_instructions(self):
		return self.get("global_instructions")

	@global_consistency_instructions.setter
	def global_consistency_instructions(self, value):
		self.set("global_instructions", value)

	def validate(self):
		if self.is_new():
			self._inherit_revision_state()

		self.continuity_mode = {
			"Independent": "Multi-shot",
			"Chained": "Continuous",
			"Consistency": "Continuous",
		}.get(self.continuity_mode, self.continuity_mode)
		if self.continuity_mode not in ("Multi-shot", "Continuous"):
			self.continuity_mode = "Multi-shot"
		self._resolve_generation_setup()
		self._validate_version_immutability()
		self._validate_timeline()
		self.validate_generation_setup()
		if self.delivery_preset in self.PRESET_DIMENSIONS:
			self.delivery_width, self.delivery_height = self.PRESET_DIMENSIONS[self.delivery_preset]
		elif self.delivery_preset == "Custom" and (
			self.delivery_width is None
			or self.delivery_height is None
			or self.delivery_width <= 0
			or self.delivery_height <= 0
		):
			frappe.throw("Custom delivery presets require a positive width and height")

	def _inherit_revision_state(self):
		"""Carry stable production settings into a new specification revision."""
		if not self.media_project or int(self.version_number or 0) <= 1:
			return

		previous_rows = frappe.get_all(
			"Media Specification",
			filters={
				"media_project": self.media_project,
				"version_number": ["<", self.version_number],
			},
			fields=["name"],
			order_by="version_number desc, creation desc",
			limit_page_length=1,
		)
		if not previous_rows:
			return

		previous = frappe.get_doc("Media Specification", previous_rows[0].name)
		for fieldname in self.REVISION_FIELDS:
			current_value = self.get(fieldname)
			previous_value = previous.get(fieldname)
			if fieldname == "continuity_mode":
				if previous_value:
					self.set(fieldname, previous_value)
			elif current_value in (None, "", 0) and previous_value not in (None, ""):
				self.set(fieldname, previous_value)

		if not self.planning_context_hash:
			self.planning_context_hash = previous.planning_context_hash
			self.planning_context_json = previous.planning_context_json

		if not (self.get("audio_cues") or []):
			for row in previous.get("audio_cues") or []:
				self.append(
					"audio_cues",
					{
						"role": row.role,
						"asset_version": row.asset_version,
						"start_seconds": row.start_seconds,
						"end_seconds": row.end_seconds,
						"gain_db": row.gain_db,
						"fade_in_seconds": row.fade_in_seconds,
						"fade_out_seconds": row.fade_out_seconds,
						"duck_others": row.duck_others,
					},
				)

	def _resolve_generation_setup(self):
		if self.workflow:
			return
		workflow_doc = get_latest_valid_workflow()
		if not workflow_doc:
			frappe.throw(_("No default Generation Workflow is configured."))
		self.workflow = workflow_doc.name

	def validate_generation_setup(self):
		if self.status != "Ready":
			return
		if not self.workflow:
			frappe.throw(_("Ready Media Specifications require a Workflow."))
		workflow_version = frappe.get_doc("Generation Workflow", self.workflow)
		from joymedia.services.workflow_resolver import validate_workflow_bindings
		validate_workflow_bindings(workflow_version)

	def on_update(self):
		if self.has_value_changed("total_duration_seconds"):
			from joymedia.services.shot_duration_planner import recalculate_shot_durations
			recalculate_shot_durations(self.name)

	def _validate_timeline(self):
		if (self.total_duration_seconds or 0) <= 0:
			frappe.throw(_("Total Duration must be greater than zero."))
		if self.workflow:
			workflow_version = frappe.get_doc("Generation Workflow", self.workflow)
			if (workflow_version.output_fps or 0) <= 0:
				frappe.throw(_("Workflow output FPS must be greater than zero."))

	def _validate_version_immutability(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in self.IDENTITY_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(_("Media Specification {0} cannot be changed after creation.").format(fieldname))
		if previous.status != "Draft" and self.status == "Draft":
			frappe.throw(_("A Ready, Superseded, or Archived Media Specification cannot return to Draft."))
		if not self._execution_has_started():
			return
		for fieldname in self.EXECUTION_CONTRACT_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(
					_("Execution contract field {0} cannot change after Generation Jobs or Runs exist.").format(fieldname)
				)

	def _execution_has_started(self):
		if frappe.db.exists("Generation Run", {"media_specification": self.name}):
			return True
		shot_names = frappe.get_all(
			"Shot Specification", filters={"media_specification": self.name}, pluck="name"
		)
		return bool(
			shot_names
			and frappe.db.exists("Generation Job", {"shot_specification": ["in", shot_names]})
		)
