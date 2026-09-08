# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now


FINAL_REVIEW_STATUSES = ("Approved", "Rejected", "Needs Revision")
SCORE_FIELDS = (
	"visual_quality_score",
	"identity_score",
	"temporal_consistency_score",
	"prompt_adherence_score",
)


class QualityReview(Document):
	def validate(self):
		self._validate_attempt_artifact_context()
		self._validate_failure_class()
		self._validate_scores()
		if self.review_type == "Human" and not self.reviewer:
			frappe.throw(_("Human Quality Reviews require a Reviewer."))
		if self.status in FINAL_REVIEW_STATUSES and not self.reviewed_at:
			self.reviewed_at = now()

	def after_insert(self):
		self._apply_review_outcome()

	def on_update(self):
		self._apply_review_outcome()

	def _apply_review_outcome(self):
		if self.status not in FINAL_REVIEW_STATUSES:
			return

		shot = frappe.get_doc("Shot Specification", self.shot_specification)
		if self.status == "Approved":
			from joymedia.services.artifact_service import promote_artifact

			asset_version = promote_artifact(self.generation_artifact)["asset_version"]
			self.db_set("asset_version", asset_version, update_modified=False)
			shot.selected_output_asset_version = asset_version
		elif self.status == "Rejected":
			artifact = frappe.get_doc("Generation Artifact", self.generation_artifact)
			if artifact.lifecycle_status in ("Temporary", "Retained"):
				artifact.lifecycle_status = "Expired"
				artifact.save(ignore_permissions=True)
			if artifact.promoted_asset_version and shot.selected_output_asset_version == artifact.promoted_asset_version:
				shot.selected_output_asset_version = None
			else:
				return
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
			["generation_job", "output_artifact", "status"],
			as_dict=True,
		)
		if not attempt or attempt.status != "Completed":
			frappe.throw(_("Quality Review requires a completed Generation Attempt."))
		attempt_shot = frappe.db.get_value("Generation Job", attempt.generation_job, "shot_specification")
		if attempt_shot != self.shot_specification:
			frappe.throw(_("Quality Review Shot Specification must match the Generation Attempt."))
		artifact_attempt = frappe.db.get_value(
			"Generation Artifact", self.generation_artifact, "generation_attempt"
		)
		if artifact_attempt != self.generation_attempt or attempt.output_artifact != self.generation_artifact:
			frappe.throw(_("Quality Review Generation Artifact must match the Generation Attempt output."))

	def _validate_failure_class(self):
		if not self.failure_class:
			return
		failure_class_field = frappe.get_meta("Generation Attempt").get_field("failure_class")
		valid_failure_classes = set((failure_class_field.options or "").splitlines())
		if self.failure_class not in valid_failure_classes:
			frappe.throw(_("Quality Review Failure Class must use the Generation Attempt taxonomy."))

	def _validate_scores(self):
		for fieldname in SCORE_FIELDS:
			value = self.get(fieldname)
			if value in (None, ""):
				continue
			try:
				score = float(value)
			except (TypeError, ValueError):
				frappe.throw(_("{0} must be a number from 0.0 to 1.0.").format(fieldname))
			if not 0.0 <= score <= 1.0:
				frappe.throw(_("{0} must be from 0.0 to 1.0.").format(fieldname))


@frappe.whitelist()
def regenerate_shot_from_ui(quality_review_name: str, reason: str = "Human Review Rejection"):
	"""Create and submit one QA retry for a rejected review's completed Attempt."""
	frappe.has_permission("Quality Review", "write", quality_review_name, throw=True)
	review = frappe.get_doc("Quality Review", quality_review_name)
	if review.status != "Rejected":
		frappe.throw(_("Only rejected Quality Reviews can regenerate a Shot."))

	from joymedia.joymedia.doctype.generation_attempt.generation_attempt import create_qa_retry_attempt
	from joymedia.services.generation_runner import submit_attempt

	retry_attempt = create_qa_retry_attempt(review.generation_attempt, reason)
	submission = submit_attempt(retry_attempt.name)
	frappe.db.commit()
	return {
		"name": retry_attempt.name,
		"status": frappe.db.get_value("Generation Attempt", retry_attempt.name, "status"),
		"deferred": bool(submission and submission.get("deferred")),
	}
