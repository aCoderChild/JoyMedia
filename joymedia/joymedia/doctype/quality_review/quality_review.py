# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now


FINAL_REVIEW_STATUSES = ("Approved", "Rejected", "Needs Revision")


class QualityReview(Document):
	def validate(self):
		self._validate_attempt_artifact_context()
		self._validate_failure_class()
		if self.review_type == "Human" and not self.reviewer:
			frappe.throw(_("Human Quality Reviews require a Reviewer."))
		if self.status in FINAL_REVIEW_STATUSES and not self.reviewed_at:
			self.reviewed_at = now()

	def on_update(self):
		shot = frappe.get_doc("Shot Specification", self.shot_specification)
		if self.status == "Approved":
			shot.selected_output_asset_version = self.asset_version
		elif shot.selected_output_asset_version == self.asset_version:
			shot.selected_output_asset_version = None
		else:
			return
		shot.save(ignore_permissions=True)
		if self.status == "Approved":
			job_name = frappe.db.get_value("Generation Attempt", self.generation_attempt, "generation_job")
			run_name = frappe.db.get_value("Generation Job", job_name, "generation_run")
			if run_name:
				from joymedia.services.generation_orchestrator import enqueue_finalization_if_ready

				enqueue_finalization_if_ready(run_name)

	def _validate_attempt_artifact_context(self):
		attempt = frappe.db.get_value(
			"Generation Attempt",
			self.generation_attempt,
			["generation_job", "output_asset_version", "status"],
			as_dict=True,
		)
		if not attempt or attempt.status != "Completed":
			frappe.throw(_("Quality Review requires a completed Generation Attempt."))
		attempt_shot = frappe.db.get_value("Generation Job", attempt.generation_job, "shot_specification")
		if attempt_shot != self.shot_specification:
			frappe.throw(_("Quality Review Shot Specification must match the Generation Attempt."))
		if attempt.output_asset_version != self.asset_version:
			frappe.throw(_("Quality Review Asset Version must match the Generation Attempt output."))

	def _validate_failure_class(self):
		if not self.failure_class:
			return
		failure_class_field = frappe.get_meta("Generation Attempt").get_field("failure_class")
		valid_failure_classes = set((failure_class_field.options or "").splitlines())
		if self.failure_class not in valid_failure_classes:
			frappe.throw(_("Quality Review Failure Class must use the Generation Attempt taxonomy."))
