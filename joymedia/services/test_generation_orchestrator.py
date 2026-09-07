from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import generation_orchestrator


class TestGenerationOrchestrator(FrappeTestCase):
	@patch("joymedia.services.generation_orchestrator._enqueue")
	@patch("joymedia.services.generation_orchestrator.frappe.has_permission")
	@patch("joymedia.services.generation_orchestrator.frappe.get_doc")
	def test_start_run_only_queues_background_preparation(self, get_doc, has_permission, enqueue):
		run = MagicMock()
		run.name = "RUN-00001"
		run.status = "Draft"
		run.media_specification = "SPEC-00001"
		media_specification = frappe._dict(name="SPEC-00001", status="Ready")
		get_doc.side_effect = [run, media_specification]

		result = generation_orchestrator.start_run(run.name)

		has_permission.assert_called_once_with("Generation Run", "write", run.name, throw=True)
		self.assertEqual(run.status, "Queued")
		run.save.assert_called_once_with(ignore_permissions=True)
		enqueue.assert_called_once_with("prepare_run", run.name)
		self.assertEqual(result["status"], "Queued")

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_refresh_run_counters_are_derived_from_jobs(self, get_all):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		get_all.return_value = [
			frappe._dict(status="Completed"),
			frappe._dict(status="Completed"),
			frappe._dict(status="Running"),
			frappe._dict(status="Queued"),
		]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.total_jobs, 4)
		self.assertEqual(run.completed_jobs, 2)
		self.assertEqual(run.failed_jobs, 0)
		self.assertEqual(run.running_jobs, 1)
		self.assertEqual(run.progress, 50)
		self.assertEqual(run.status, "Running")
		run.save.assert_called_once_with(ignore_permissions=True)

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_job_is_partially_completed_when_terminal_attempts_include_successes_and_failures(self, get_all):
		job = frappe._dict(name="JOB-00001", requested_variants=2, completed_at=None)
		job.save = MagicMock()
		get_all.return_value = [
			frappe._dict(name="ATT-00001", status="Completed", retry_of=None),
			frappe._dict(name="ATT-00002", status="Failed", retry_of=None),
		]

		generation_orchestrator._update_job_summary(job)

		self.assertEqual(job.successful_variants, 1)
		self.assertEqual(job.failed_variants, 1)
		self.assertEqual(job.progress, 50)
		self.assertEqual(job.status, "Partially Completed")
		self.assertEqual(job.error_summary, "Only 1 of 2 requested variants completed.")

	@patch("joymedia.services.generation_orchestrator._enqueue")
	@patch("joymedia.services.generation_orchestrator._run_outputs_are_selected", return_value=True)
	def test_completed_run_with_selected_outputs_queues_finalization(self, outputs_are_selected, enqueue):
		run = frappe._dict(
			name="RUN-00001", status="Completed", auto_compose=1, final_asset_version=None
		)

		generation_orchestrator._enqueue_finalization_if_ready(run)

		outputs_are_selected.assert_called_once_with(run.name)
		enqueue.assert_called_once_with("finalize_run", run.name)
