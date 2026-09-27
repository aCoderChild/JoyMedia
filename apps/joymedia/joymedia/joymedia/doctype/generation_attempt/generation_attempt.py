# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now


QA_RETRY_REASONS = {"QA Failure", "Human Review Rejection"}


class GenerationAttempt(Document):
	def before_insert(self):
		job = frappe.get_doc("Generation Job", self.generation_job)
		if job.status != "Queued":
			frappe.throw(
				_("Generation Job {0} must be Queued before a Generation Attempt can be created.").format(
					self.generation_job
				)
			)
		job.validate_for_execution()
		self._validate_retry_reference()
		latest_attempt_number = frappe.db.get_value(
			"Generation Attempt",
			{"generation_job": self.generation_job},
			[{"MAX": "attempt_number"}],
		)
		self.attempt_number = (latest_attempt_number or 0) + 1

	def _validate_retry_reference(self):
		if not self.retry_of:
			if self.retry_reason:
				frappe.throw(_("Retry Reason requires Retry Of."))
			return

		previous_attempt = frappe.db.get_value(
			"Generation Attempt",
			self.retry_of,
			["generation_job", "status"],
			as_dict=True,
		)
		if not previous_attempt or previous_attempt.generation_job != self.generation_job:
			frappe.throw(_("Retry Of must belong to the same Generation Job."))
		if not self.retry_reason:
			frappe.throw(_("Retry Reason is required when Retry Of is set."))

		_validate_retry_reason(self.retry_reason)
		if previous_attempt.status == "Failed":
			return
		if previous_attempt.status == "Completed" and self.retry_reason in QA_RETRY_REASONS:
			return
		frappe.throw(
			_("Retry Of must be a failed Generation Attempt, unless this is a QA retry of a completed Attempt.")
		)


@frappe.whitelist()
def create_retry_attempt(failed_attempt_name: str, reason: str):
	"""Create a new Pending attempt linked to one failed attempt."""
	frappe.has_permission("Generation Attempt", "create", throw=True)
	return create_retry_attempt_internal(failed_attempt_name, reason)


def create_retry_attempt_internal(failed_attempt_name: str, reason: str):
	"""Create a retry after the caller has authorized the owning workflow."""
	reason = (reason or "").strip()
	_validate_retry_reason(reason)
	failed_attempt = frappe.get_doc("Generation Attempt", failed_attempt_name)
	if failed_attempt.status != "Failed":
		frappe.throw(_("Only failed Generation Attempts can be retried."))

	return _create_successor_attempt(failed_attempt, reason)


def create_qa_retry_attempt(completed_attempt_name: str, reason: str = "Human Review Rejection"):
	"""Create a Pending QA successor for a completed Attempt rejected in review."""
	frappe.has_permission("Generation Attempt", "create", throw=True)
	return create_qa_retry_attempt_internal(completed_attempt_name, reason)


def create_qa_retry_attempt_internal(
	completed_attempt_name: str, reason: str = "Human Review Rejection"
):
	"""Create a QA retry after the caller has authorized the owning Campaign."""
	reason = (reason or "").strip()
	if reason not in QA_RETRY_REASONS:
		frappe.throw(_("QA retries must use QA Failure or Human Review Rejection."))
	_validate_retry_reason(reason)
	completed_attempt = frappe.get_doc("Generation Attempt", completed_attempt_name)
	if completed_attempt.status != "Completed":
		frappe.throw(_("Only completed Generation Attempts can be retried after QA review."))
	if frappe.db.exists("Generation Attempt", {"retry_of": completed_attempt.name}):
		frappe.throw(_("Generation Attempt {0} already has a retry successor.").format(completed_attempt.name))
	return _create_successor_attempt(completed_attempt, reason)


def _create_successor_attempt(previous_attempt, reason):
	job = frappe.get_doc("Generation Job", previous_attempt.generation_job)
	if job.status not in ("Ready", "Queued", "Completed", "Partially Completed", "Failed"):
		frappe.throw(
			_("Generation Job {0} cannot be retried from status {1}.").format(job.name, job.status)
		)

	job.status = "Queued"
	job.queued_at = now()
	job.save(ignore_permissions=True)

	retry_attempt = frappe.get_doc(
		{
			"doctype": "Generation Attempt",
			"generation_job": job.name,
			"seed": previous_attempt.seed,
			"retry_of": previous_attempt.name,
			"retry_reason": reason,
			"status": "Pending",
		}
	).insert(ignore_permissions=True)
	if job.generation_run:
		from joymedia.services.generation_orchestrator import refresh_generation_state_for_attempt

		refresh_generation_state_for_attempt(retry_attempt.name)
	return retry_attempt


def _validate_retry_reason(reason):
	valid_reasons = {
		value
		for value in (frappe.get_meta("Generation Attempt").get_field("retry_reason").options or "").splitlines()
		if value
	}
	if reason not in valid_reasons:
		frappe.throw(_("Retry Reason must use the Generation Attempt retry taxonomy."))
