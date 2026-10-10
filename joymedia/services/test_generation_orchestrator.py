from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import generation_orchestrator


class TestGenerationOrchestrator(FrappeTestCase):
	def test_continuous_pipeline_uses_previous_video_last_frame_for_next_shot(self):
		steps = [
			frappe._dict(step_key="keyframe", consumes_artifact_role=None),
			frappe._dict(step_key="video", consumes_artifact_role="Primary Image"),
		]

		first_shot = generation_orchestrator._pipeline_steps_for_segment(steps)
		following_shot = generation_orchestrator._pipeline_steps_for_segment(
			steps,
			previous_shot_tail_job="TASK-PREVIOUS-VIDEO",
			cross_shot_continuity=True,
		)

		self.assertEqual(["keyframe", "video"], [stage[0].step_key for stage in first_shot])
		self.assertTrue(first_shot[0][3])
		self.assertEqual(1, len(following_shot))
		self.assertEqual("video", following_shot[0][0].step_key)
		self.assertEqual("TASK-PREVIOUS-VIDEO", following_shot[0][1])
		self.assertEqual("Last Frame", following_shot[0][2])
		self.assertFalse(following_shot[0][3])

	def test_pipeline_keeps_full_stages_for_independent_shots(self):
		steps = [
			frappe._dict(step_key="keyframe", consumes_artifact_role=None),
			frappe._dict(step_key="video", consumes_artifact_role="Primary Image"),
		]

		stages = generation_orchestrator._pipeline_steps_for_segment(
			steps,
			previous_shot_tail_job="TASK-PREVIOUS-VIDEO",
			cross_shot_continuity=False,
		)

		self.assertEqual(["keyframe", "video"], [stage[0].step_key for stage in stages])
		self.assertIsNone(stages[0][1])

	@patch(
		"joymedia.services.workflow_resolver.get_workflow_input_contract",
		return_value=[{
			"role": "keyframe_reference",
			"accepted_media_type": "Image",
			"allow_multiple": True,
			"max_count": 0,
		}],
	)
	def test_pipeline_reference_inputs_treat_zero_max_count_as_unbounded(self, get_contract):
		shot = {
			"references": [
				{"asset_version": "ASTV-00001", "reference_role": "Product"},
				{"asset_version": "ASTV-00002", "reference_role": "Character"},
				{"asset_version": "ASTV-00003", "reference_role": "Environment"},
			]
		}
		workflow = frappe._dict(name="WF-TEST")

		result = generation_orchestrator._pipeline_reference_inputs(shot, workflow)

		self.assertEqual(
			{"keyframe_reference": ["ASTV-00001", "ASTV-00002", "ASTV-00003"]},
			result,
		)
		get_contract.assert_called_once_with(workflow)

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

	@patch("joymedia.services.generation_orchestrator._finish_film")
	@patch("joymedia.services.generation_orchestrator.sync_media_project_status_for_run")
	@patch("joymedia.services.generation_orchestrator._refresh_run_counters")
	@patch("joymedia.services.generation_orchestrator._create_retry_attempt", return_value=False)
	@patch("joymedia.services.generation_orchestrator._has_submittable_work", return_value=False)
	@patch("joymedia.services.generation_orchestrator._finalize_completed_shots")
	@patch("joymedia.services.generation_orchestrator._get_run_job_names", return_value=[])
	def test_run_completion_finishes_the_film_once(self, job_names, finalize, submittable, retry, refresh_counters, sync_status, finish_film):
		run = frappe._dict(name="RUN-00001", media_project="PRJ-00001", status="Running")
		refresh_counters.side_effect = lambda run: run.update(status="Completed")

		generation_orchestrator._advance_run(run)
		generation_orchestrator._advance_run(run)

		finish_film.assert_called_once_with("PRJ-00001")

	@patch("joymedia.services.generation_orchestrator.frappe.get_all")
	def test_first_segments_are_submitted_before_continuations(self, get_all):
		get_all.return_value = [
			frappe._dict(name="T1", workflow="R2V"), frappe._dict(name="T1b", workflow="CONT"),
			frappe._dict(name="T2", workflow="R2V"), frappe._dict(name="T2b", workflow="CONT"),
			frappe._dict(name="T3", workflow="R2V"),
		]

		self.assertEqual(["T1", "T2", "T3", "T1b", "T2b"], generation_orchestrator._submission_order("RUN-1"))

	@patch("joymedia.services.generation_orchestrator.frappe.db.count", return_value=1)
	@patch("joymedia.services.generation_orchestrator._get_run_job_names", return_value=["T1", "T2"])
	def test_submission_capacity_allows_only_one_in_flight_attempt(self, job_names, count):
		run = frappe._dict(name="RUN-1")

		self.assertFalse(generation_orchestrator._has_submission_capacity(run))
		count.assert_called_once_with(
			"Generation Attempt",
			{"generation_task": ["in", ["T1", "T2"]], "status": ["in", ["Queued", "Running"]]},
		)
