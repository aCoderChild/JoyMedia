# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now


MANUAL_REGENERATION_REASONS = {"Manual Retry", "Reroll"}


class GenerationAttempt(Document):
	def before_insert(self):
		job = frappe.get_doc("Generation Task", self.generation_task)
		if job.status != "Queued":
			frappe.throw(
				_("Generation Task {0} must be Queued before a Generation Attempt can be created.").format(
					self.generation_task
				)
			)
		if not self.retry_of and frappe.db.exists(
			"Generation Attempt", {"generation_task": self.generation_task}
		):
			frappe.throw(_("A Generation Task can have only one initial Generation Attempt."))
		job.validate_for_execution()
		self._validate_retry_reference()
		latest_attempt_number = frappe.db.get_value(
			"Generation Attempt",
			{"generation_task": self.generation_task},
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
			["generation_task", "status"],
			as_dict=True,
		)
		if not previous_attempt or previous_attempt.generation_task != self.generation_task:
			frappe.throw(_("Retry Of must belong to the same Generation Task."))
		if frappe.db.exists(
			"Generation Attempt",
			{"retry_of": self.retry_of, "name": ["!=", self.name]},
		):
			frappe.throw(_("A Generation Attempt can have only one retry successor."))
		if not self.retry_reason:
			frappe.throw(_("Retry Reason is required when Retry Of is set."))

		_validate_retry_reason(self.retry_reason)
		if previous_attempt.status == "Failed":
			return
		if previous_attempt.status == "Completed" and self.retry_reason in MANUAL_REGENERATION_REASONS:
			return
		frappe.throw(
			_("Retry Of must be a failed Generation Attempt, unless this is a manual regeneration of a completed Attempt.")
		)


def get_effective_attempt_from_history(attempts):
	"""Return the leaf Attempt in a Job's linear retry chain."""
	if not attempts:
		return None
	successors = {}
	for attempt in attempts:
		if attempt.retry_of:
			successors.setdefault(attempt.retry_of, []).append(attempt)
	for previous_name, children in successors.items():
		if len(children) > 1:
			frappe.throw(_("Generation Attempt {0} has more than one retry successor.").format(previous_name))
	leaf_attempts = [attempt for attempt in attempts if attempt.name not in successors]
	if len(leaf_attempts) != 1:
		frappe.throw(_("Generation Task has an invalid Generation Attempt lineage."))
	return leaf_attempts[0]


def get_effective_attempt(job_name):
	attempts = frappe.get_all(
		"Generation Attempt",
		filters={"generation_task": job_name},
		fields=["name", "status", "retry_of", "failure_class", "error_summary", "error_details"],
		order_by="attempt_number asc, creation asc",
	)
	return get_effective_attempt_from_history(attempts)


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


def _invalidate_manual_regeneration_outputs(job):
	"""Invalidate generation completion and any explicit project export before rerolling.

	A manual reroll replaces part of the effective execution lineage. Generated
	Shot outputs are re-materialized by the run, while a previously exported
	project video becomes stale until the user exports the edited timeline again.
	"""
	if not job.generation_run:
		return

	run = frappe.get_doc("Generation Run", job.generation_run)
	frappe.db.set_value(
		"Generation Run",
		run.name,
		{
			"completed_at": None,
			"failure_class": None,
			"error_summary": None,
		},
		update_modified=False,
	)

	media_project = run.media_project
	if media_project:
		from joymedia.services.timeline_editor import _invalidate_project_output

		_invalidate_project_output(media_project)


def _create_successor_attempt(previous_attempt, reason):
	job = frappe.get_doc("Generation Task", previous_attempt.generation_task)
	if job.status not in ("Ready", "Queued", "Completed", "Failed"):
		frappe.throw(
			_("Generation Task {0} cannot be retried from status {1}.").format(job.name, job.status)
		)

	if reason in MANUAL_REGENERATION_REASONS:
		_invalidate_manual_regeneration_outputs(job)

	job.status = "Queued"
	job.queued_at = now()
	job.save(ignore_permissions=True)

	retry_attempt = frappe.get_doc(
		{
			"doctype": "Generation Attempt",
			"generation_task": job.name,
			"seed": (
				secrets.randbelow(2_147_483_648)
				if reason in MANUAL_REGENERATION_REASONS
				else previous_attempt.seed
			),
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