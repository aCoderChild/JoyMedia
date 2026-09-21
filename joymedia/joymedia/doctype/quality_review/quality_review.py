# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now


FINAL_STATUSES = {"Approved", "Rejected"}


class QualityReview(Document):
	def validate(self):
		self._validate_artifact_context()
		self._validate_status_transition()
		self._validate_finalization()

	def on_update(self):
		previous = self.get_doc_before_save()
		if not previous or previous.status == self.status:
			return
		if self.status in FINAL_STATUSES:
			self._apply_review_outcome()

	def _validate_artifact_context(self):
		if not self.generation_artifact:
			frappe.throw(_("Quality Review requires a Generation Artifact."))

		artifact = frappe.get_doc("Generation Artifact", self.generation_artifact)
		if not artifact.generation_attempt:
			frappe.throw(
				_("Generation Artifact {0} has no Generation Attempt.").format(artifact.name)
			)

		attempt = frappe.get_doc("Generation Attempt", artifact.generation_attempt)
		if attempt.status != "Completed":
			frappe.throw(_("Only completed Generation Attempts can be reviewed."))
		if attempt.output_artifact != artifact.name:
			frappe.throw(_("Generation Artifact does not match the Attempt output."))

	def _validate_status_transition(self):
		if self.is_new():
			if self.status != "Pending":
				frappe.throw(_("New Quality Reviews must start as Pending."))
			return

		previous = self.get_doc_before_save()
		if previous and previous.status in FINAL_STATUSES and self.status != previous.status:
			frappe.throw(_("A completed review decision cannot be changed."))

	def _validate_finalization(self):
		if self.status not in FINAL_STATUSES:
			return
		if not self.reviewer:
			frappe.throw(_("Reviewer is required."))
		if not self.reviewed_at:
			frappe.throw(_("Reviewed At is required."))

	def _get_context(self):
		artifact = frappe.get_doc("Generation Artifact", self.generation_artifact)
		attempt = frappe.get_doc("Generation Attempt", artifact.generation_attempt)
		job = frappe.get_doc("Generation Job", attempt.generation_job)
		shot = frappe.get_doc("Shot Specification", job.shot_specification)
		return artifact, attempt, job, shot

	def _apply_review_outcome(self):
		artifact, attempt, job, shot = self._get_context()
		if self.status == "Approved":
			self._approve_artifact(artifact, attempt, job, shot)
		elif self.status == "Rejected":
			self._reject_artifact(artifact, shot)

	def _approve_artifact(self, artifact, attempt, job, shot):
		if self.asset_version:
			return

		from joymedia.services.artifact_service import promote_artifact

		asset_version = promote_artifact(artifact.name)["asset_version"]
		self.db_set("asset_version", asset_version, update_modified=False)
		shot.selected_output_asset_version = asset_version
		shot.save(ignore_permissions=True)

		if job.generation_run:
			from joymedia.services.generation_orchestrator import enqueue_finalization_if_ready

			enqueue_finalization_if_ready(job.generation_run)

	def _reject_artifact(self, artifact, shot):
		if (
			artifact.promoted_asset_version
			and shot.selected_output_asset_version == artifact.promoted_asset_version
		):
			shot.selected_output_asset_version = None
			shot.save(ignore_permissions=True)


@frappe.whitelist()
def approve_review(review_name: str):
	frappe.has_permission("Quality Review", "write", review_name, throw=True)
	return approve_review_internal(review_name)


def approve_review_internal(review_name: str):
	review = frappe.get_doc("Quality Review", review_name)
	if review.status != "Pending":
		frappe.throw(_("Only Pending reviews can be approved."))
	review.status = "Approved"
	review.reviewer = frappe.session.user
	review.reviewed_at = now()
	review.save(ignore_permissions=True)
	return {"name": review.name, "status": review.status, "asset_version": review.asset_version}


@frappe.whitelist()
def reject_review(review_name: str, notes: str | None = None):
	frappe.has_permission("Quality Review", "write", review_name, throw=True)
	return reject_review_internal(review_name, notes)


def reject_review_internal(review_name: str, notes: str | None = None):
	review = frappe.get_doc("Quality Review", review_name)
	if review.status != "Pending":
		frappe.throw(_("Only Pending reviews can be rejected."))
	review.status = "Rejected"
	review.reviewer = frappe.session.user
	review.reviewed_at = now()
	if notes:
		review.notes = notes.strip()
	review.save(ignore_permissions=True)
	return {"name": review.name, "status": review.status}


@frappe.whitelist()
def regenerate_shot_from_ui(quality_review_name: str, reason: str = "Human Review Rejection"):
	"""Create and submit one QA retry for a rejected review's completed Attempt."""
	frappe.has_permission("Quality Review", "write", quality_review_name, throw=True)
	return regenerate_shot_internal(quality_review_name, reason)


def regenerate_shot_internal(
	quality_review_name: str, reason: str = "Human Review Rejection"
):
	"""Create and submit a QA retry after the caller has authorized the Campaign."""
	review = frappe.get_doc("Quality Review", quality_review_name)
	if review.status != "Rejected":
		frappe.throw(_("Only rejected Quality Reviews can regenerate a Shot."))
	artifact = frappe.get_doc("Generation Artifact", review.generation_artifact)

	from joymedia.joymedia.doctype.generation_attempt.generation_attempt import create_qa_retry_attempt
	from joymedia.services.generation_runner import submit_attempt

	retry_attempt = create_qa_retry_attempt(artifact.generation_attempt, reason)
	submission = submit_attempt(retry_attempt.name)
	frappe.db.commit()
	return {
		"name": retry_attempt.name,
		"status": frappe.db.get_value("Generation Attempt", retry_attempt.name, "status"),
		"deferred": bool(submission and submission.get("deferred")),
	}
