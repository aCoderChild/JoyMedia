from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import generation_orchestrator


class TestGenerationOrchestrator(FrappeTestCase):
	@patch("joymedia.services.generation_orchestrator.filelock", return_value=nullcontext())
	@patch("joymedia.services.generation_orchestrator.frappe.db.commit")
	@patch("joymedia.services.generation_orchestrator.refresh_generation_state_for_attempt")
	@patch("joymedia.services.generation_orchestrator._submit_attempt_or_record_failure")
	@patch("joymedia.services.generation_orchestrator.create_retry_attempt_internal")
	@patch("joymedia.services.generation_orchestrator._get_job_attempts")
	@patch("joymedia.services.generation_orchestrator.frappe.get_doc")
	@patch("joymedia.services.generation_orchestrator.frappe.has_permission")
	def test_job_retry_creates_and_submits_only_latest_failed_attempts(
		self,
		has_permission,
		get_doc,
		get_job_attempts,
		create_retry_attempt,
		submit_attempt,
		refresh_state,
		commit,
		filelock,
	):
		job = frappe._dict(name="JOB-00001", status="Failed")
		created_attempt = frappe._dict(name="ATT-00003", status="Queued")
		get_doc.side_effect = [job, created_attempt]
		get_job_attempts.return_value = [
			frappe._dict(name="ATT-00001", status="Failed", retry_of=None),
			frappe._dict(name="ATT-00002", status="Failed", retry_of="ATT-00001"),
		]
		create_retry_attempt.return_value = created_attempt
		submit_attempt.return_value = {"prompt_id": "comfy-123"}

		result = generation_orchestrator.retry_generation_task_from_ui(job.name, "Execution Failure")

		has_permission.assert_called_once_with("Generation Task", "write", job.name, throw=True)
		create_retry_attempt.assert_called_once_with("ATT-00002", "Execution Failure")
		submit_attempt.assert_called_once_with("ATT-00003")
		refresh_state.assert_called_once_with("ATT-00003")
		commit.assert_called_once_with()
		self.assertEqual(result["attempts"], [{"name": "ATT-00003", "status": "Queued", "deferred": False}])

	@patch("joymedia.services.generation_orchestrator.filelock", return_value=nullcontext())
	@patch("joymedia.services.generation_orchestrator.frappe.db.commit")
	@patch("joymedia.services.generation_orchestrator._retry_and_submit_latest_failed_attempts")
	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	@patch("joymedia.services.generation_orchestrator.frappe.get_doc")
	@patch("joymedia.services.generation_orchestrator.frappe.has_permission")
	def test_run_retry_submits_attempts_only_for_failed_jobs(
		self,
		has_permission,
		get_doc,
		get_all,
		retry_and_submit,
		commit,
		filelock,
	):
		run = MagicMock(name="RUN-00001", status="Failed", completed_at="2026-09-08")
		run.name = "RUN-00001"
		run.status = "Failed"
		job = MagicMock(name="JOB-00002", status="Failed", completed_at="2026-09-08")
		job.name = "JOB-00002"
		get_doc.side_effect = [run, job]
		get_all.return_value = ["JOB-00002"]
		retry_and_submit.return_value = [
			{"name": "ATT-00002", "status": "Queued", "deferred": False}
		]

		result = generation_orchestrator.retry_failed_jobs_from_ui(run.name)

		has_permission.assert_called_once_with("Generation Run", "write", run.name, throw=True)
		retry_and_submit.assert_called_once_with(job, "Execution Failure")
		self.assertEqual("Queued", result["attempts"][0]["status"])
		run.reload.assert_called_once()
		commit.assert_called_once_with()

	@patch("joymedia.services.generation_orchestrator.frappe.enqueue")
	@patch("joymedia.services.generation_orchestrator.frappe.db.get_value", return_value="JOB-00002")
	def test_enqueue_submit_run_uses_job_specific_deduplication(self, get_value, enqueue):
		generation_orchestrator._enqueue_submit_run("RUN-00001")

		enqueue.assert_called_once_with(
			"joymedia.services.generation_orchestrator.submit_run",
			queue="long",
			run_name="RUN-00001",
			enqueue_after_commit=True,
			job_id="joymedia:submit_run:RUN-00001:JOB-00002",
			deduplicate=True,
		)

	@patch("joymedia.services.generation_orchestrator._enqueue")
	@patch("joymedia.services.generation_orchestrator.validate_generation_preflight")
	@patch("joymedia.services.generation_orchestrator.frappe.has_permission")
	@patch("joymedia.services.generation_orchestrator.frappe.get_doc")
	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_start_run_only_queues_background_preparation(
		self,
		get_all,
		get_doc,
		has_permission,
		validate_generation_preflight,
		enqueue,
	):
		run = MagicMock()
		run.name = "RUN-00001"
		run.status = "Draft"
		run.media_project = "PROJ-00001"
		run.workflow = "WF-00001"
		project = frappe._dict(name="PROJ-00001", status="Draft", workflow="WF-00001", generation_mode="Multi-shot")
		project.validate_generation_setup = MagicMock()
		workflow = frappe._dict(name="WF-00001")
		get_doc.side_effect = [run, project, workflow]
		get_all.return_value = []

		result = generation_orchestrator.start_run(run.name)

		has_permission.assert_called_once_with("Generation Run", "write", run.name, throw=True)
		validate_generation_preflight.assert_called_once_with(
			project,
			workflow,
			[],
			check_comfyui=True,
		)
		self.assertEqual(run.status, "Queued")
		run.db_set.assert_called_once_with(
			{"status": "Queued", "error_summary": None},
			update_modified=False,
		)
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

		self.assertEqual(run.total_tasks, 4)
		self.assertEqual(run.completed_tasks, 2)
		self.assertEqual(run.failed_tasks, 0)
		self.assertEqual(run.running_tasks, 1)
		self.assertEqual(run.progress, 50)
		self.assertEqual(run.status, "Running")
		run.db_set.assert_called_once()
		self.assertEqual(run.db_set.call_args.args[0]["status"], "Running")

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_ready_jobs_leave_a_run_queued_until_an_attempt_is_submitted(self, get_all):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		get_all.return_value = [frappe._dict(status="Ready")]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.status, "Queued")
		self.assertEqual(run.running_tasks, 0)

	@patch("joymedia.services.generation_orchestrator.frappe.db.exists", return_value=True)
	@patch(
		"joymedia.services.generation_orchestrator._get_pending_attempt_names_for_run",
		return_value=[],
	)
	def test_ready_job_is_submittable_work(self, pending_attempts, exists):
		self.assertTrue(generation_orchestrator._has_submittable_work("RUN-00001"))
		exists.assert_called_once_with(
			"Generation Task", {"generation_run": "RUN-00001", "status": "Ready"}
		)

	@patch("joymedia.services.generation_orchestrator._run_outputs_are_selected", return_value=False)
	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_completed_execution_stays_running_until_shot_outputs_exist(self, get_all, outputs_are_selected):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		get_all.return_value = [frappe._dict(status="Completed"), frappe._dict(status="Completed")]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.status, "Running")
		self.assertIsNone(run.completed_at)

	@patch("joymedia.services.generation_orchestrator._run_outputs_are_selected", return_value=True)
	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_completed_execution_with_selected_outputs_completes_run(self, get_all, outputs_are_selected):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		get_all.return_value = [frappe._dict(status="Completed")]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.status, "Completed")
		self.assertIsNotNone(run.completed_at)

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_failed_attempt_followed_by_completed_attempt_completes_job(self, get_all):
		job = frappe._dict(name="JOB-00001", completed_at=None)
		job.db_set = MagicMock()
		get_all.return_value = [
			frappe._dict(name="ATT-00001", status="Failed", retry_of=None),
			frappe._dict(name="ATT-00002", status="Completed", retry_of="ATT-00001"),
		]

		generation_orchestrator._update_job_summary(job)

		self.assertEqual(job.progress, 100)
		self.assertEqual(job.status, "Completed")
		self.assertIsNone(job.error_summary)
		job.db_set.assert_called_once()

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_manual_regeneration_replaces_the_rejected_completed_attempt(self, get_all):
		job = frappe._dict(name="JOB-00001", completed_at=None)
		job.db_set = MagicMock()
		get_all.return_value = [
			frappe._dict(
				name="ATT-00001", status="Completed", retry_of=None, retry_reason=None
			),
			frappe._dict(
				name="ATT-00002",
				status="Pending",
				retry_of="ATT-00001",
				retry_reason="Manual Retry",
			),
		]

		generation_orchestrator._update_job_summary(job)

		self.assertEqual(job.status, "Queued")

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_job_summary_uses_the_latest_failed_attempt_details(self, get_all):
		job = frappe._dict(name="JOB-00001", completed_at=None)
		job.db_set = MagicMock()
		get_all.return_value = [
			frappe._dict(
				name="ATT-00001",
				status="Failed",
				retry_of=None,
				failure_class="Input",
				error_summary="No staged input was available.",
			)
		]

		generation_orchestrator._update_job_summary(job)

		self.assertEqual("Failed", job.status)
		self.assertEqual("Input", job.failure_class)
		self.assertEqual("No staged input was available.", job.error_summary)
		job.db_set.assert_called_once()

	@patch("joymedia.services.generation_orchestrator._refresh_run_counters")
	@patch("joymedia.services.generation_orchestrator._enqueue")
	@patch("joymedia.services.generation_orchestrator.frappe.get_doc")
	def test_generation_completion_does_not_enqueue_project_export(self, get_doc, enqueue, refresh_counters):
		run = frappe._dict(name="RUN-00001", status="Completed")
		get_doc.return_value = run

		generation_orchestrator.enqueue_finalization_if_ready(run.name)

		refresh_counters.assert_called_once_with(run)
		enqueue.assert_not_called()

	def test_generation_finalization_endpoint_is_removed(self):
		with self.assertRaises(frappe.ValidationError):
			generation_orchestrator.finalize_run("RUN-00001")
