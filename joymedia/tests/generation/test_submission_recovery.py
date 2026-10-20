"""Recovery cannot regress a completion observed while ComfyUI is queried."""

from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from joymedia.services.generation.runner import reconcile_attempt_submission, submit_attempt


class TestSubmissionRecovery(TestCase):
	def attempt(self, status, prompt=None):
		return frappe._dict(
			name="ATT-RECOVERY-TEST", status=status, external_job_id=prompt,
			submission_token="stable-test-token", comfyui_endpoint_url="http://comfy:8188",
			queued_at=None, save=MagicMock(),
		)

	def test_a_submitting_attempt_reuses_its_existing_lock_without_resubmitting(self):
		depth, acquisitions = 0, []

		@contextmanager
		def nonreentrant_lock(name):
			nonlocal depth
			self.assertEqual(0, depth, "recovery reacquired its own non-reentrant lock")
			depth += 1
			acquisitions.append(name)
			try:
				yield
			finally:
				depth -= 1

		attempt = self.attempt("Submitting")
		with patch("joymedia.services.generation.runner.filelock", nonreentrant_lock), patch(
			"joymedia.services.generation.runner.frappe.get_doc", return_value=attempt
		), patch("joymedia.services.generation.runner.find_prompt_by_client_id", return_value="real-prompt"), patch(
			"joymedia.services.generation.runner.submit_workflow"
		) as submit, patch.object(frappe.db, "commit"), patch("joymedia.services.generation.runner.now", return_value="2026-01-01 00:00:00"):
			result = submit_attempt(attempt.name)
		self.assertEqual("real-prompt", result["prompt_id"])
		self.assertEqual(1, len(acquisitions))
		submit.assert_not_called()

	def test_network_reconciliation_cannot_overwrite_a_terminal_state(self):
		for status in ("Completed", "Failed", "Cancelled"):
			with self.subTest(status=status):
				stale = self.attempt("Submitting")
				current = self.attempt(status, "original-prompt")
				with patch("joymedia.services.generation.runner.filelock"), patch(
					"joymedia.services.generation.runner.frappe.get_doc", side_effect=[stale, current]
				), patch("joymedia.services.generation.runner.find_prompt_by_client_id", return_value="late-prompt"), patch.object(frappe.db, "commit"):
					result = reconcile_attempt_submission(stale.name)
				self.assertEqual({"status": status, "prompt_id": "original-prompt"}, result)
				current.save.assert_not_called()

	def test_a_terminal_attempt_is_not_queried_or_resubmitted(self):
		attempt = self.attempt("Completed", "existing-prompt")
		with patch("joymedia.services.generation.runner.filelock"), patch(
			"joymedia.services.generation.runner.frappe.get_doc", return_value=attempt
		), patch("joymedia.services.generation.runner.find_prompt_by_client_id") as find, patch.object(frappe.db, "commit"):
			result = reconcile_attempt_submission(attempt.name)
		self.assertEqual({"status": "Completed", "prompt_id": "existing-prompt"}, result)
		find.assert_not_called()
