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
	@patch("joymedia.services.generation_orchestrator.create_retry_attempt")
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

		result = generation_orchestrator.retry_generation_job_from_ui(job.name, "Execution Failure")

		has_permission.assert_called_once_with("Generation Job", "write", job.name, throw=True)
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
	def test_enqueue_deduplicates_each_run_operation(self, enqueue):
		generation_orchestrator._enqueue("submit_run", "RUN-00001")

		enqueue.assert_called_once_with(
			"joymedia.services.generation_orchestrator.submit_run",
			queue="long",
			run_name="RUN-00001",
			enqueue_after_commit=True,
			job_id="joymedia:submit_run:RUN-00001",
			deduplicate=True,
		)

	@patch("joymedia.services.generation_orchestrator.select_worker", return_value=None)
	@patch("joymedia.services.generation_orchestrator.has_configured_workers", return_value=True)
	def test_full_managed_worker_pool_does_not_schedule_an_immediate_retry(
		self, has_configured_workers, select_worker
	):
		run = frappe._dict(name="RUN-00001", workflow_version="WFV-00001")

		self.assertFalse(generation_orchestrator._has_submission_capacity(run))
		select_worker.assert_called_once_with("WFV-00001")

	@patch("joymedia.services.generation_orchestrator.select_worker")
	@patch("joymedia.services.generation_orchestrator.has_configured_workers", return_value=False)
	def test_legacy_endpoint_has_submission_capacity_without_workers(
		self, has_configured_workers, select_worker
	):
		run = frappe._dict(name="RUN-00001", workflow_version="WFV-00001")

		self.assertTrue(generation_orchestrator._has_submission_capacity(run))
		select_worker.assert_not_called()

	@patch("joymedia.services.generation_orchestrator._enqueue")
	@patch("joymedia.services.generation_orchestrator.frappe.has_permission")
	@patch("joymedia.services.generation_orchestrator.frappe.get_doc")
	@patch("joymedia.services.shot_duration_planner.recalculate_shot_durations")
	def test_start_run_only_queues_background_preparation(
		self, recalculate_shot_durations, get_doc, has_permission, enqueue
	):
		run = MagicMock()
		run.name = "RUN-00001"
		run.status = "Draft"
		run.media_specification = "SPEC-00001"
		media_specification = frappe._dict(name="SPEC-00001", status="Ready")
		media_specification.validate_generation_setup = MagicMock()
		get_doc.side_effect = [run, media_specification]

		result = generation_orchestrator.start_run(run.name)

		has_permission.assert_called_once_with("Generation Run", "write", run.name, throw=True)
		recalculate_shot_durations.assert_called_once_with(media_specification.name)
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
		self.assertEqual(run.running_jobs, 0)

	@patch("joymedia.services.generation_orchestrator.frappe.db.exists", return_value=True)
	@patch(
		"joymedia.services.generation_orchestrator._get_pending_attempt_names_for_run",
		return_value=[],
	)
	def test_ready_job_is_submittable_work(self, pending_attempts, exists):
		self.assertTrue(generation_orchestrator._has_submittable_work("RUN-00001"))
		exists.assert_called_once_with(
			"Generation Job", {"generation_run": "RUN-00001", "status": "Ready"}
		)

	@patch("joymedia.services.generation_orchestrator._run_outputs_are_selected", return_value=False)
	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_completed_execution_awaits_output_review(self, get_all, outputs_are_selected):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		run.final_asset_version = None
		run.auto_compose = 1
		get_all.return_value = [frappe._dict(status="Completed"), frappe._dict(status="Completed")]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.status, "Awaiting Review")
		self.assertIsNone(run.completed_at)
		outputs_are_selected.assert_called_once_with(run.name)

	@patch("joymedia.services.generation_orchestrator._run_outputs_are_selected", return_value=True)
	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_approved_outputs_move_a_run_to_finalizing(self, get_all, outputs_are_selected):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		run.final_asset_version = None
		run.auto_compose = 1
		get_all.return_value = [frappe._dict(status="Completed")]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.status, "Finalizing")
		self.assertIsNone(run.completed_at)

	@patch("joymedia.services.generation_orchestrator._run_outputs_are_selected", return_value=True)
	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_approved_outputs_are_ready_for_manual_composition(self, get_all, outputs_are_selected):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		run.final_asset_version = None
		run.auto_compose = 0
		get_all.return_value = [frappe._dict(status="Completed")]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.status, "Ready for Composition")
		self.assertIsNone(run.completed_at)

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_job_is_partially_completed_when_terminal_attempts_include_successes_and_failures(self, get_all):
		job = frappe._dict(name="JOB-00001", requested_variants=2, completed_at=None)
		job.db_set = MagicMock()
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
		job.db_set.assert_called_once()

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_qa_retry_replaces_the_rejected_completed_variant(self, get_all):
		job = frappe._dict(name="JOB-00001", requested_variants=1, completed_at=None)
		job.db_set = MagicMock()
		get_all.return_value = [
			frappe._dict(
				name="ATT-00001", status="Completed", retry_of=None, retry_reason=None
			),
			frappe._dict(
				name="ATT-00002",
				status="Pending",
				retry_of="ATT-00001",
				retry_reason="Human Review Rejection",
			),
		]

		generation_orchestrator._update_job_summary(job)

		self.assertEqual(job.successful_variants, 0)
		self.assertEqual(job.status, "Queued")

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_job_summary_uses_the_latest_failed_attempt_details(self, get_all):
		job = frappe._dict(name="JOB-00001", requested_variants=1, completed_at=None)
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

	@patch("joymedia.services.generation_orchestrator._enqueue")
	@patch("joymedia.services.generation_orchestrator._run_outputs_are_selected", return_value=True)
	def test_finalizing_run_with_selected_outputs_queues_finalization(self, outputs_are_selected, enqueue):
		run = frappe._dict(
			name="RUN-00001", status="Finalizing", auto_compose=1, final_asset_version=None
		)

		generation_orchestrator._enqueue_finalization_if_ready(run)

		outputs_are_selected.assert_called_once_with(run.name)
		enqueue.assert_called_once_with("finalize_run", run.name)

	@patch("joymedia.services.generation_orchestrator.compose_media_specification")
	@patch("joymedia.services.generation_orchestrator.refresh_run")
	@patch("joymedia.services.generation_orchestrator.frappe.get_doc")
	def test_finalization_sets_completed_only_after_composition(
		self, get_doc, refresh_run, compose_media_specification
	):
		run = MagicMock()
		run.name = "RUN-00001"
		run.status = "Finalizing"
		run.media_specification = "SPEC-00001"
		run.final_asset_version = None
		get_doc.return_value = run
		compose_media_specification.return_value = {"final_asset_version": "ASTV-00001"}

		generation_orchestrator.finalize_run(run.name)

		refresh_run.assert_called_once_with(run.name, enqueue_finalization=False)
		compose_media_specification.assert_called_once_with("SPEC-00001")
		self.assertEqual(run.status, "Completed")
		self.assertEqual(run.final_asset_version, "ASTV-00001")
		self.assertIsNotNone(run.completed_at)
		run.save.assert_called_once_with(ignore_permissions=True)

	@patch("joymedia.services.generation_orchestrator.compose_media_specification")
	@patch("joymedia.services.generation_orchestrator.refresh_run")
	@patch("joymedia.services.generation_orchestrator.frappe.get_doc")
	def test_manual_composition_accepts_ready_for_composition(
		self, get_doc, refresh_run, compose_media_specification
	):
		run = MagicMock()
		run.name = "RUN-00001"
		run.status = "Ready for Composition"
		run.media_specification = "SPEC-00001"
		run.final_asset_version = None
		get_doc.return_value = run
		compose_media_specification.return_value = {"final_asset_version": "ASTV-00001"}

		generation_orchestrator.finalize_run(run.name)

		self.assertEqual(run.status, "Completed")
		self.assertEqual(run.final_asset_version, "ASTV-00001")
