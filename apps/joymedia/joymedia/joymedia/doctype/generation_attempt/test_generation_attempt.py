from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from .generation_attempt import GenerationAttempt, create_qa_retry_attempt, create_retry_attempt
from joymedia.services.generation_runner import submit_attempt


class TestGenerationAttempt(FrappeTestCase):
	def test_attempt_number_is_assigned_from_the_job_history(self):
		attempt = frappe.new_doc("Generation Attempt")
		attempt.generation_job = "JOB-00001"
		attempt.seed = 42
		job = MagicMock(status="Queued")

		with (
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.get_doc",
				return_value=job,
			) as get_doc,
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.db.get_value",
				return_value=3,
			) as get_value,
		):
			GenerationAttempt.before_insert(attempt)

		self.assertEqual(attempt.attempt_number, 4)
		job.validate_for_execution.assert_called_once()
		get_value.assert_called_once_with(
			"Generation Attempt",
			{"generation_job": "JOB-00001"},
			[{"MAX": "attempt_number"}],
		)

	def test_create_retry_attempt_creates_a_pending_successor(self):
		failed_attempt = frappe._dict(
			name="ATT-00001", status="Failed", generation_job="JOB-00001", seed=42
		)
		job = frappe._dict(name="JOB-00001", status="Failed")
		job.save = MagicMock()
		retry_attempt = MagicMock()
		retry_attempt.insert.return_value = retry_attempt

		with (
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.has_permission"
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt._validate_retry_reason"
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.get_doc",
				side_effect=[failed_attempt, job, retry_attempt],
			) as get_doc,
		):
			result = create_retry_attempt(failed_attempt.name, "Execution Failure")

		self.assertIs(result, retry_attempt)
		self.assertEqual(job.status, "Queued")
		job.save.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(
			get_doc.call_args_list[2].args[0],
			{
				"doctype": "Generation Attempt",
				"generation_job": "JOB-00001",
				"seed": 42,
				"retry_of": "ATT-00001",
				"retry_reason": "Execution Failure",
				"status": "Pending",
			},
		)
		retry_attempt.insert.assert_called_once_with(ignore_permissions=True)

	def test_partially_completed_job_can_create_a_retry_attempt(self):
		failed_attempt = frappe._dict(
			name="ATT-00001", status="Failed", generation_job="JOB-00001", seed=42
		)
		job = frappe._dict(name="JOB-00001", status="Partially Completed")
		job.save = MagicMock()
		retry_attempt = MagicMock()
		retry_attempt.insert.return_value = retry_attempt

		with (
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.has_permission"
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt._validate_retry_reason"
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.get_doc",
				side_effect=[failed_attempt, job, retry_attempt],
			),
		):
			result = create_retry_attempt(failed_attempt.name, "Execution Failure")

		self.assertIs(result, retry_attempt)
		self.assertEqual("Queued", job.status)

	def test_completed_attempt_can_create_one_qa_retry_successor(self):
		completed_attempt = frappe._dict(
			name="ATT-00001", status="Completed", generation_job="JOB-00001", seed=42
		)
		job = frappe._dict(name="JOB-00001", status="Completed")
		job.save = MagicMock()
		retry_attempt = MagicMock()
		retry_attempt.insert.return_value = retry_attempt

		with (
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.has_permission"
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt._validate_retry_reason"
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.db.exists",
				return_value=False,
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.get_doc",
				side_effect=[completed_attempt, job, retry_attempt],
			) as get_doc,
		):
			result = create_qa_retry_attempt(completed_attempt.name, "Human Review Rejection")

		self.assertIs(result, retry_attempt)
		self.assertEqual(job.status, "Queued")
		self.assertEqual(
			get_doc.call_args_list[2].args[0]["retry_reason"], "Human Review Rejection"
		)
		self.assertEqual(get_doc.call_args_list[2].args[0]["retry_of"], completed_attempt.name)

	def test_failed_attempt_cannot_be_submitted_again(self):
		attempt = frappe._dict(name="ATT-00001", status="Failed")
		with patch("joymedia.services.generation_runner.frappe.get_doc", return_value=attempt):
			with self.assertRaises(frappe.ValidationError):
				submit_attempt(attempt.name)
