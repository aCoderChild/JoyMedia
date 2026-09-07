from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation_runner import submit_attempt


class TestGenerationRunner(FrappeTestCase):
	@patch("joymedia.services.generation_runner._stage_generation_inputs")
	@patch("joymedia.services.generation_runner.has_configured_workers", return_value=True)
	@patch("joymedia.services.generation_runner.select_worker", return_value=None)
	@patch("joymedia.services.generation_runner.frappe.get_doc")
	def test_attempt_stays_pending_when_managed_workers_have_no_capacity(
		self, get_doc, select_worker, has_configured_workers, stage_generation_inputs
	):
		attempt = frappe._dict(name="ATT-00001", status="Pending", generation_job="JOB-00001")
		job = MagicMock(workflow_version="WFV-00001")
		get_doc.side_effect = [attempt, job]

		result = submit_attempt(attempt.name)

		self.assertEqual(result["deferred"], True)
		self.assertEqual(attempt.status, "Pending")
		stage_generation_inputs.assert_not_called()

	@patch("joymedia.services.generation_runner.refresh_worker")
	@patch("joymedia.services.generation_runner.submit_workflow", return_value={"prompt_id": "comfy-1"})
	@patch("joymedia.services.generation_runner.get_base_url", return_value="http://legacy:8188")
	@patch("joymedia.services.generation_runner.resolve_attempt", return_value={})
	@patch("joymedia.services.generation_runner._stage_generation_inputs", return_value={})
	@patch("joymedia.services.generation_runner.has_configured_workers", return_value=False)
	@patch("joymedia.services.generation_runner.select_worker", return_value=None)
	@patch("joymedia.services.generation_runner.frappe.get_doc")
	def test_legacy_endpoint_is_used_only_when_no_workers_are_configured(
		self,
		get_doc,
		select_worker,
		has_configured_workers,
		stage_generation_inputs,
		resolve_attempt,
		get_base_url,
		submit_workflow,
		refresh_worker,
	):
		attempt = frappe._dict(name="ATT-00001", status="Pending", generation_job="JOB-00001")
		attempt.reload = MagicMock()
		attempt.save = MagicMock()
		job = MagicMock(workflow_version="WFV-00001")
		get_doc.side_effect = [attempt, job]

		result = submit_attempt(attempt.name)

		self.assertEqual(result, {"prompt_id": "comfy-1"})
		stage_generation_inputs.assert_called_once_with(job, None)
		get_base_url.assert_called_once_with()
		submit_workflow.assert_called_once_with({}, base_url="http://legacy:8188")
		self.assertEqual(attempt.status, "Queued")
		self.assertIsNone(attempt.comfyui_worker)
		refresh_worker.assert_not_called()
