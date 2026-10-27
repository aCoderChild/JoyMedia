from contextlib import nullcontext
from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation import orchestrator as generation_orchestrator


class TestGenerationOrchestrator(FrappeTestCase):
	def test_last_frame_is_only_an_explicit_destination_constraint(self):
		from joymedia.services.generation.preparation import explicit_last_frame_assets

		shot = frappe._dict(
			references=[
				{"reference_role": "Character", "asset_version": "AV-MASCOT"},
				{"reference_role": "last_frame", "asset_version": "AV-END"},
			]
		)
		self.assertEqual(["AV-END"], explicit_last_frame_assets(shot))
		self.assertEqual([], explicit_last_frame_assets(frappe._dict(references=shot.references[:1])))

	@patch("joymedia.services.generation.orchestrator._get_run_job_names")
	@patch("joymedia.services.generation.orchestrator._has_submittable_work", return_value=True)
	@patch("joymedia.services.generation.orchestrator.frappe.db.get_value")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_fair_dispatch_handles_runs_with_and_without_a_datetime_dispatch(
		self,
		get_all,
		get_value,
		has_submittable_work,
		get_run_job_names,
	):
		get_all.return_value = [
			frappe._dict(name="RUN-OLDER", creation=datetime(2026, 10, 10, 10, 0, 0)),
			frappe._dict(name="RUN-NEW", creation=datetime(2026, 10, 10, 11, 0, 0)),
		]
		get_value.side_effect = [datetime(2026, 10, 10, 10, 30, 0), None]
		get_run_job_names.side_effect = [["TASK-OLDER"], ["TASK-NEW"]]

		self.assertEqual("RUN-NEW", generation_orchestrator._next_fair_run_name())

	@patch("joymedia.services.generation.orchestrator._get_run_job_names")
	@patch("joymedia.services.generation.orchestrator._has_submittable_work", return_value=True)
	@patch("joymedia.services.generation.orchestrator.frappe.db.get_value")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_workflow_affinity_is_bounded_by_two_dispatches(
		self, get_all, get_value, has_submittable_work, get_run_job_names
	):
		runs = [
			frappe._dict(name="RUN-OLDER", creation=datetime(2026, 10, 10, 9, 0)),
			frappe._dict(name="RUN-NEWER", creation=datetime(2026, 10, 10, 9, 1)),
		]
		recent = [frappe._dict(generation_task="TASK-NEWER")]
		get_all.side_effect = lambda doctype, **kwargs: runs if doctype == "Generation Run" else recent
		get_run_job_names.side_effect = lambda run: ["TASK-OLDER"] if run == "RUN-OLDER" else ["TASK-NEWER"]

		def value(doctype, key, field, **kwargs):
			if doctype == "Generation Attempt":
				return datetime(2026, 10, 10, 9, 30 if key["generation_task"] == ["TASK-OLDER"] else 31)
			if isinstance(key, dict):
				return "IMAGE" if key["generation_run"] == "RUN-OLDER" else "VIDEO"
			return "VIDEO"

		get_value.side_effect = value
		self.assertEqual("RUN-NEWER", generation_orchestrator._next_fair_run_name())
		recent.append(frappe._dict(generation_task="TASK-NEWER"))
		self.assertEqual("RUN-OLDER", generation_orchestrator._next_fair_run_name())

	@patch("joymedia.services.generation.orchestrator._enqueue_submit_run")
	@patch("joymedia.services.generation.orchestrator._has_global_submission_capacity", return_value=True)
	@patch("joymedia.services.generation.orchestrator._next_fair_run_name", return_value="RUN-SELECTED")
	@patch("joymedia.services.generation.orchestrator.frappe.get_doc")
	def test_mismatched_submit_wakes_selected_run_without_scheduler_delay(
		self, get_doc, next_run, capacity, enqueue
	):
		get_doc.return_value = frappe._dict(name="RUN-CALLER", status="Running", total_tasks=1)
		with patch("joymedia.services.generation.orchestrator.filelock", return_value=nullcontext()):
			generation_orchestrator._submit_run_with_global_capacity("RUN-CALLER")
		enqueue.assert_called_once_with("RUN-SELECTED")

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
		self.assertTrue(stages[0][3])
		self.assertIsNone(stages[0][1])

	def test_multireference_recomposition_never_skips_its_keyframe_stage(self):
		steps = [
			frappe._dict(step_key="keyframe", consumes_artifact_role=None),
			frappe._dict(step_key="video", consumes_artifact_role="Primary Image"),
		]

		stages = generation_orchestrator._pipeline_steps_for_segment(
			steps,
			previous_shot_tail_job="TASK-PREVIOUS-VIDEO",
			cross_shot_continuity=True,
			force_full_pipeline=True,
		)

		self.assertEqual(["keyframe", "video"], [stage[0].step_key for stage in stages])

	def test_scene_reset_uses_full_pipeline_once_then_chains_segments(self):
		steps = [
			frappe._dict(step_key="keyframe", consumes_artifact_role=None),
			frappe._dict(step_key="video", consumes_artifact_role="Primary Image"),
		]
		first = generation_orchestrator._pipeline_steps_for_segment(steps, force_full_pipeline=True)
		later = generation_orchestrator._pipeline_steps_for_segment(
			steps, previous_segment_job="TASK-FIRST-VIDEO", force_full_pipeline=False
		)
		self.assertEqual(["keyframe", "video"], [stage[0].step_key for stage in first])
		self.assertEqual(["video"], [stage[0].step_key for stage in later])
		self.assertEqual("TASK-FIRST-VIDEO", later[0][1])

	@patch("joymedia.services.generation.preparation.workflow_supports_continuation", return_value=True)
	def test_long_shot_uses_workflow_declared_continuation_contract(self, supports_continuation):
		workflow = frappe._dict(
			frame_count=48,
			execution_spec='{"continuation": {"overlap_frames": 2, "new_frames": 46}}',
		)
		continuation = frappe._dict(name="WF-CONT", frame_count=48)

		segments = generation_orchestrator._segment_plan(workflow, 92, continuation)

		self.assertEqual([48, 46], [segment["segment_frame_count"] for segment in segments])
		supports_continuation.assert_called_once_with(continuation)

	@patch("joymedia.services.generation.preparation.workflow_supports_continuation", return_value=True)
	def test_segment_capacity_comes_from_the_selected_workflow(self, _supports):
		workflow = frappe._dict(frame_count=241, execution_spec="{}")
		continuation = frappe._dict(name="WF-CONT", frame_count=241)

		segments = generation_orchestrator._segment_plan(workflow, 300, continuation)

		self.assertEqual([241, 60], [segment["segment_frame_count"] for segment in segments])
		self.assertEqual(300, sum(segment["segment_effective_frames"] for segment in segments))

	@patch("joymedia.services.generation.preparation.workflow_supports_continuation", return_value=False)
	def test_long_shot_without_continuation_contract_is_rejected(self, supports_continuation):
		workflow = frappe._dict(frame_count=48, execution_spec="{}")
		with self.assertRaises(frappe.ValidationError):
			generation_orchestrator._segment_plan(workflow, 49, None)

	@patch(
		"joymedia.services.workflows.resolver.get_workflow_input_contract",
		return_value=[
			{
				"role": "keyframe_reference",
				"accepted_media_type": "Image",
				"allow_multiple": True,
				"max_count": 0,
			}
		],
	)
	def test_pipeline_reference_inputs_treat_zero_max_count_as_unbounded(self, get_contract):
		shot = {
			"character_mode": "Paste exact art",  # pictures without cutouts all go in as references
			"references": [
				{"asset_version": "ASTV-00001", "reference_role": "Product"},
				{"asset_version": "ASTV-00002", "reference_role": "Character"},
				{"asset_version": "ASTV-00003", "reference_role": "Environment"},
			],
		}
		workflow = frappe._dict(name="WF-TEST")

		result = generation_orchestrator._pipeline_reference_inputs(shot, workflow)

		self.assertEqual(
			{"keyframe_reference": ["ASTV-00001", "ASTV-00002", "ASTV-00003"]},
			result,
		)
		get_contract.assert_called_once_with(workflow)

	@patch(
		"joymedia.services.workflows.resolver.get_workflow_input_contract",
		return_value=[
			{
				"role": "product_reference",
				"accepted_media_type": "Image",
				"allow_multiple": False,
				"max_count": 2,
			}
		],
	)
	def test_pipeline_reference_inputs_preserve_direct_r2v_role(self, get_contract):
		workflow = frappe._dict(name="WF-R2V")
		result = generation_orchestrator._pipeline_reference_inputs(
			{
				"references": [
					{"asset_version": "ASTV-00001", "reference_role": "product_reference"},
					{"asset_version": "ASTV-00002", "reference_role": "product_reference"},
				]
			},
			workflow,
		)

		self.assertEqual(
			{"product_reference": ["ASTV-00001", "ASTV-00002"]},
			result,
		)

	@patch(
		"joymedia.services.workflows.resolver.get_workflow_input_contract",
		return_value=[
			{
				"role": "product_reference",
				"accepted_media_type": "Image",
				"allow_multiple": False,
				"max_count": 2,
			}
		],
	)
	def test_pipeline_reference_inputs_reject_excess_references(self, _get_contract):
		with self.assertRaises(frappe.ValidationError):
			generation_orchestrator._pipeline_reference_inputs(
				{
					"references": [
						{"asset_version": "ASTV-00001", "reference_role": "product_reference"},
						{"asset_version": "ASTV-00002", "reference_role": "product_reference"},
						{"asset_version": "ASTV-00003", "reference_role": "product_reference"},
					]
				},
				frappe._dict(name="WF-LIMITED"),
			)

	@patch("joymedia.services.generation.orchestrator._require_project_generation_authorization")
	@patch("joymedia.services.generation.orchestrator.filelock", return_value=nullcontext())
	@patch("joymedia.services.generation.orchestrator.frappe.db.commit")
	@patch("joymedia.services.generation.orchestrator.refresh_generation_state_for_attempt")
	@patch("joymedia.services.generation.orchestrator._submit_attempt_or_record_failure")
	@patch("joymedia.services.generation.orchestrator.create_retry_attempt_internal")
	@patch("joymedia.services.generation.orchestrator._get_job_attempts")
	@patch("joymedia.services.generation.orchestrator.frappe.get_doc")
	@patch("joymedia.services.generation.orchestrator.frappe.has_permission")
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
		authorize,
	):
		job = frappe._dict(name="JOB-00001", status="Failed")
		created_attempt = frappe._dict(name="ATT-00003", status="Queued")
		get_doc.side_effect = [job, frappe._dict(media_project="PROJ-00001"), frappe._dict(), created_attempt]
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

	@patch("joymedia.services.generation.orchestrator._require_project_generation_authorization")
	@patch("joymedia.services.generation.orchestrator.filelock", return_value=nullcontext())
	@patch("joymedia.services.generation.orchestrator.frappe.db.commit")
	@patch("joymedia.services.generation.orchestrator._retry_and_submit_latest_failed_attempts")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	@patch("joymedia.services.generation.orchestrator.frappe.get_doc")
	@patch("joymedia.services.generation.orchestrator.frappe.has_permission")
	def test_run_retry_submits_attempts_only_for_failed_jobs(
		self,
		has_permission,
		get_doc,
		get_all,
		retry_and_submit,
		commit,
		filelock,
		authorize,
	):
		run = MagicMock(name="RUN-00001", status="Failed", completed_at="2026-09-08")
		run.name = "RUN-00001"
		run.status = "Failed"
		job = MagicMock(name="JOB-00002", status="Failed", completed_at="2026-09-08")
		job.name = "JOB-00002"
		get_doc.side_effect = [frappe._dict(media_project="PROJ-00001"), run, job]
		get_all.return_value = ["JOB-00002"]
		retry_and_submit.return_value = [{"name": "ATT-00002", "status": "Queued", "deferred": False}]

		result = generation_orchestrator.retry_failed_jobs_from_ui(run.name)

		has_permission.assert_called_once_with("Generation Run", "write", run.name, throw=True)
		retry_and_submit.assert_called_once_with(job, "Execution Failure")
		self.assertEqual("Queued", result["attempts"][0]["status"])
		run.reload.assert_called_once()
		commit.assert_called_once_with()

	@patch("joymedia.services.generation.orchestrator.frappe.enqueue")
	@patch("joymedia.services.generation.orchestrator.frappe.db.get_value", return_value="JOB-00002")
	def test_enqueue_submit_run_uses_job_specific_deduplication(self, get_value, enqueue):
		generation_orchestrator._enqueue_submit_run("RUN-00001")

		enqueue.assert_called_once_with(
			"joymedia.services.generation.orchestrator.submit_run",
			queue="long",
			run_name="RUN-00001",
			enqueue_after_commit=True,
			job_id="joymedia:submit_run:RUN-00001:JOB-00002",
			deduplicate=True,
		)

	@patch("joymedia.services.generation.orchestrator._require_project_generation_authorization")
	@patch("joymedia.services.generation.orchestrator._enqueue")
	@patch("joymedia.services.generation.orchestrator.validate_generation_preflight")
	@patch("joymedia.services.generation.orchestrator.frappe.has_permission")
	@patch("joymedia.services.generation.orchestrator.frappe.get_doc")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_start_run_only_queues_background_preparation(
		self,
		get_all,
		get_doc,
		has_permission,
		validate_generation_preflight,
		enqueue,
		authorize,
	):
		run = MagicMock()
		run.name = "RUN-00001"
		run.status = "Draft"
		run.media_project = "PROJ-00001"
		run.workflow = "WF-00001"
		project = frappe._dict(
			name="PROJ-00001", status="Draft", workflow="WF-00001", generation_mode="Multi-shot"
		)
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

	@patch("joymedia.services.generation.orchestrator.frappe.db.set_value")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_refresh_run_counters_are_derived_from_jobs(self, get_all, set_value):
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
		set_value.assert_called_once()
		self.assertEqual(set_value.call_args.args[2]["status"], "Running")
		self.assertEqual(set_value.call_args.kwargs["update_modified"], False)

	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_ready_jobs_leave_a_run_queued_until_an_attempt_is_submitted(self, get_all):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		get_all.return_value = [frappe._dict(status="Ready")]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.status, "Queued")
		self.assertEqual(run.running_tasks, 0)

	@patch("joymedia.services.generation.orchestrator.frappe.db.count", return_value=0)
	@patch("joymedia.services.generation.orchestrator.frappe.get_all", return_value=["TASK-READY"])
	@patch(
		"joymedia.services.generation.orchestrator._get_pending_attempt_names_for_run",
		return_value=[],
	)
	def test_ready_job_is_submittable_work(self, pending_attempts, get_all, count):
		self.assertTrue(generation_orchestrator._has_submittable_work("RUN-00001"))
		get_all.assert_called_once_with(
			"Generation Task",
			filters={"generation_run": "RUN-00001", "status": ["in", ["Ready", "Queued"]]},
			pluck="name",
		)

	@patch("joymedia.services.generation.orchestrator.frappe.db.count", return_value=0)
	@patch("joymedia.services.generation.orchestrator.frappe.get_all", return_value=["TASK-QUEUED"])
	@patch("joymedia.services.generation.orchestrator._get_pending_attempt_names_for_run", return_value=[])
	def test_queued_task_without_an_attempt_remains_dispatchable(self, pending, get_all, count):
		self.assertTrue(generation_orchestrator._has_submittable_work("RUN-00001"))
		count.assert_called_once_with("Generation Attempt", {"generation_task": "TASK-QUEUED"})

	@patch("joymedia.services.generation.run_state._run_outputs_are_selected", return_value=False)
	@patch("joymedia.services.generation.orchestrator.frappe.db.set_value")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_completed_execution_stays_running_until_shot_outputs_exist(
		self, get_all, set_value, outputs_are_selected
	):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		get_all.return_value = [frappe._dict(status="Completed"), frappe._dict(status="Completed")]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.status, "Running")
		self.assertIsNone(run.completed_at)

	@patch("joymedia.services.generation.run_state._run_outputs_are_selected", return_value=True)
	@patch("joymedia.services.generation.orchestrator.frappe.db.set_value")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_completed_execution_with_selected_outputs_completes_run(
		self, get_all, set_value, outputs_are_selected
	):
		run = MagicMock()
		run.name = "RUN-00001"
		run.completed_at = None
		get_all.return_value = [frappe._dict(status="Completed")]

		generation_orchestrator._refresh_run_counters(run)

		self.assertEqual(run.status, "Completed")
		self.assertIsNotNone(run.completed_at)

	@patch("joymedia.services.generation.orchestrator.frappe.db.set_value")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_failed_attempt_followed_by_completed_attempt_completes_job(self, get_all, set_value):
		job = frappe._dict(name="JOB-00001", completed_at=None)
		get_all.return_value = [
			frappe._dict(name="ATT-00001", status="Failed", retry_of=None),
			frappe._dict(name="ATT-00002", status="Completed", retry_of="ATT-00001"),
		]

		generation_orchestrator._update_job_summary(job)

		self.assertEqual(job.progress, 100)
		self.assertEqual(job.status, "Completed")
		self.assertIsNone(job.error_summary)
		self.assertEqual("Generation Task", set_value.call_args.args[0])
		self.assertEqual("Completed", set_value.call_args.args[2]["status"])

	def test_polling_completed_task_does_not_rewrite_unchanged_summary(self):
		job = frappe._dict(name="JOB", status="Completed", progress=100, completed_at="2026-10-20 00:00:00")
		with (
			patch.object(
				generation_orchestrator,
				"_get_job_attempts",
				return_value=[frappe._dict(name="ATT", status="Completed")],
			),
			patch.object(frappe.db, "set_value") as write,
		):
			generation_orchestrator._update_job_summary(job)
		write.assert_not_called()

	@patch("joymedia.services.generation.orchestrator.frappe.db.set_value")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_manual_regeneration_replaces_the_rejected_completed_attempt(self, get_all, set_value):
		job = frappe._dict(name="JOB-00001", completed_at=None)
		get_all.return_value = [
			frappe._dict(name="ATT-00001", status="Completed", retry_of=None, retry_reason=None),
			frappe._dict(
				name="ATT-00002",
				status="Pending",
				retry_of="ATT-00001",
				retry_reason="Manual Retry",
			),
		]

		generation_orchestrator._update_job_summary(job)

		self.assertEqual(job.status, "Queued")

	@patch("joymedia.services.generation.orchestrator.frappe.db.set_value")
	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_job_summary_uses_the_latest_failed_attempt_details(self, get_all, set_value):
		job = frappe._dict(name="JOB-00001", completed_at=None)
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
		self.assertEqual("Failed", set_value.call_args.args[2]["status"])

	@patch(
		"joymedia.services.editing.post_production.resume_post_production", return_value={"status": "Queued"}
	)
	def test_generation_completion_treats_pending_human_qa_as_expected(self, resume):
		self.assertEqual({"status": "Queued"}, generation_orchestrator._finish_film("PRJ-00001"))
		resume.assert_called_once_with("PRJ-00001")

	@patch("joymedia.services.generation.orchestrator._finish_film")
	@patch("joymedia.services.generation.orchestrator.sync_media_project_status_for_run")
	@patch("joymedia.services.generation.orchestrator._refresh_run_counters")
	@patch("joymedia.services.generation.orchestrator._create_retry_attempt", return_value=False)
	@patch("joymedia.services.generation.orchestrator._has_submittable_work", return_value=False)
	@patch("joymedia.services.generation.orchestrator._finalize_completed_shots")
	@patch("joymedia.services.generation.orchestrator._get_run_job_names", return_value=[])
	def test_run_completion_finishes_the_film_once(
		self, job_names, finalize, submittable, retry, refresh_counters, sync_status, finish_film
	):
		run = frappe._dict(name="RUN-00001", media_project="PRJ-00001", status="Running", reload=MagicMock())
		refresh_counters.side_effect = lambda run: run.update(status="Completed")

		generation_orchestrator._advance_run(run)
		generation_orchestrator._advance_run(run)

		finish_film.assert_called_once_with("PRJ-00001")

	@patch("joymedia.services.generation.orchestrator.frappe.get_all")
	def test_first_segments_are_submitted_before_continuations(self, get_all):
		get_all.return_value = [
			frappe._dict(name="T1", workflow="R2V"),
			frappe._dict(name="T1b", workflow="CONT"),
			frappe._dict(name="T2", workflow="R2V"),
			frappe._dict(name="T2b", workflow="CONT"),
			frappe._dict(name="T3", workflow="R2V"),
		]

		self.assertEqual(["T1", "T2", "T3", "T1b", "T2b"], generation_orchestrator._submission_order("RUN-1"))

	@patch("joymedia.services.generation.orchestrator.frappe.db.count", return_value=1)
	@patch("joymedia.services.generation.orchestrator._get_run_job_names", return_value=["T1", "T2"])
	def test_submission_capacity_allows_only_one_in_flight_attempt(self, job_names, count):
		run = frappe._dict(name="RUN-1")

		self.assertFalse(generation_orchestrator._has_submission_capacity(run))
		count.assert_called_once_with(
			"Generation Attempt",
			{"generation_task": ["in", ["T1", "T2"]], "status": ["in", ["Submitting", "Queued", "Running"]]},
		)

	@patch("joymedia.services.generation.orchestrator.frappe.db.get_value", return_value="Multi-shot")
	def test_independent_jobs_can_use_configured_parallel_capacity(self, get_value):
		run = frappe._dict(name="RUN-1", media_project="PRJ-1")
		with patch.dict(frappe.conf, {"joymedia_max_independent_jobs_per_run": 3}):
			self.assertEqual(3, generation_orchestrator._run_submission_limit(run))

	@patch("joymedia.services.generation.orchestrator.frappe.db.get_value", return_value="Continuous")
	def test_continuous_jobs_remain_serial_despite_parallel_configuration(self, get_value):
		run = frappe._dict(name="RUN-1", media_project="PRJ-1")
		with patch.dict(frappe.conf, {"joymedia_max_independent_jobs_per_run": 3}):
			self.assertEqual(1, generation_orchestrator._run_submission_limit(run))


class TestDrawModeInputs(FrappeTestCase):
	def test_in_draw_mode_only_one_character_picture_goes_in(self):
		from unittest.mock import patch

		from joymedia.services.generation.orchestrator import _pipeline_reference_inputs
		from joymedia.services.keyframes import overlay as subject_overlay

		contract = [
			{"role": "character", "max_count": 1, "accepted_media_type": "Image", "allow_multiple": False},
			{"role": "product", "max_count": 1, "accepted_media_type": "Image", "allow_multiple": False},
		]
		shot = frappe._dict(
			character_mode="Draw in scene",
			references=[
				{"reference_role": "Character", "asset_version": "AV1"},
				{"reference_role": "Character", "asset_version": "AV2"},
				{"reference_role": "Product", "asset_version": "AV3"},
				{"reference_role": "Logo", "asset_version": "AV4"},
			],
		)
		with (
			patch("joymedia.services.workflows.resolver.get_workflow_input_contract", return_value=contract),
			patch.object(subject_overlay, "_cutout_path", return_value="/x.png"),
		):
			# One character picture goes in (the board combines the rest); the product is drawn from the text and the logo
			# is laid over the film, so neither is an input of the image model.
			self.assertEqual({"character": ["AV1"]}, _pipeline_reference_inputs(shot, frappe._dict(name="W")))

	def test_a_real_person_and_a_mascot_are_different_inputs_of_the_image_stage(self):
		from unittest.mock import patch

		from joymedia.services.generation.orchestrator import _pipeline_reference_inputs
		from joymedia.services.keyframes import overlay as subject_overlay

		contract = [
			{"role": "character", "max_count": 1, "accepted_media_type": "Image", "allow_multiple": False},
			{"role": "person", "max_count": 1, "accepted_media_type": "Image", "allow_multiple": False},
		]
		shot = frappe._dict(
			character_mode="Draw in scene",
			references=[
				{"reference_role": "Person", "asset_version": "AVP"},
				{"reference_role": "Character", "asset_version": "AVC"},
			],
		)
		with (
			patch("joymedia.services.workflows.resolver.get_workflow_input_contract", return_value=contract),
			patch.object(subject_overlay, "_cutout_path", return_value=None),
		):
			self.assertEqual(
				{"person": ["AVP"], "character": ["AVC"]},
				_pipeline_reference_inputs(shot, frappe._dict(name="W")),
			)

	def test_an_opaque_product_is_sent_to_the_dedicated_product_input(self):
		from unittest.mock import patch

		from joymedia.services.generation.orchestrator import _pipeline_reference_inputs
		from joymedia.services.keyframes import overlay as subject_overlay

		contract = [
			{"role": "character", "max_count": 1, "accepted_media_type": "Image", "allow_multiple": False},
			{"role": "product", "max_count": 1, "accepted_media_type": "Image", "allow_multiple": False},
		]
		shot = frappe._dict(
			character_mode="Draw in scene",
			references=[
				{"reference_role": "Character", "asset_version": "AVC"},
				{"reference_role": "Product", "asset_version": "AVP"},
			],
		)
		with (
			patch("joymedia.services.workflows.resolver.get_workflow_input_contract", return_value=contract),
			patch.object(subject_overlay, "_cutout_path", return_value=None),
		):
			self.assertEqual(
				{"character": ["AVC"], "product": ["AVP"]},
				_pipeline_reference_inputs(shot, frappe._dict(name="W")),
			)


class TestLastFramePolicy(FrappeTestCase):
	def test_no_tuning_option_forces_a_later_segment_back_to_its_opening_keyframe(self):
		from joymedia.services.project.tuning import DEFAULTS

		self.assertNotIn("anchor_continuation_to_keyframe", DEFAULTS)


class TestFrozenVideoSeed(FrappeTestCase):
	def test_video_replay_seed_is_frozen_in_run_scope(self):
		with patch.object(frappe.db, "get_value", side_effect=["Video", '{"video_seed":1234}']):
			self.assertEqual(
				1234,
				generation_orchestrator._initial_seed(
					frappe._dict(workflow="workflow", generation_run="run")
				),
			)

	def test_invalid_replay_seeds_are_not_coerced(self):
		for seed in [True, -1, 2147483648, "123", 1.5]:
			with (
				self.subTest(seed=seed),
				patch.object(
					frappe.db,
					"get_value",
					side_effect=["Video", __import__("json").dumps({"video_seed": seed})],
				),
			):
				with self.assertRaises(ValueError):
					generation_orchestrator._initial_seed(
						frappe._dict(workflow="workflow", generation_run="run")
					)


class TestResultTransactionBoundary(FrappeTestCase):
	def test_status_changes_commit_before_expensive_finalization(self):
		run = MagicMock(name="run")
		run.name = "RUN"
		run.status = "Running"
		order = []

		def fail_after_boundary(run):
			order.append("render")
			raise ValueError("stop after boundary")

		with (
			patch.object(frappe.db, "commit", side_effect=lambda: order.append("commit")),
			patch.object(frappe.db, "set_value"),
			patch.object(frappe, "clear_last_message"),
			patch.object(frappe, "get_doc", return_value=MagicMock()),
			patch.object(generation_orchestrator, "_get_run_job_names", return_value=["TASK"]),
			patch.object(
				generation_orchestrator, "_update_job_summary", side_effect=lambda job: order.append("status")
			),
			patch.object(
				generation_orchestrator,
				"_finalize_completed_shots",
				side_effect=fail_after_boundary,
			),
			patch.object(generation_orchestrator, "_refresh_run_counters"),
			patch.object(generation_orchestrator, "sync_media_project_status_for_run"),
			patch.object(generation_orchestrator, "_run_summary", return_value={}),
		):
			generation_orchestrator._advance_run(run)
		self.assertLess(order.index("status"), order.index("render"))
		self.assertIn("commit", order[order.index("status") + 1 : order.index("render")])


class TestSceneFinalizationIsolation(FrappeTestCase):
	def test_one_held_composition_does_not_abandon_the_other_scenes(self):
		orchestrator = generation_orchestrator
		run = frappe._dict(
			name="RUN", execution_scope_json="{}", project_snapshot_json="{}", media_project="P"
		)
		completed = [frappe._dict(status="Completed")]
		with (
			patch.object(orchestrator, "_is_keyframe_run", return_value=False),
			patch.object(orchestrator, "_keeps_selected_output", return_value=False),
			patch("joymedia.services.consistency.retention.needs_candidate_review", return_value=False),
			patch("frappe.get_all", side_effect=[["A", "B"], completed, completed]),
			patch.object(
				orchestrator, "compose_shot_segments", side_effect=[ValueError("held composition"), None]
			) as compose,
			patch.object(orchestrator, "_hold_composition") as hold,
		):
			orchestrator._finalize_completed_shots(run)
		self.assertEqual(2, compose.call_count)
		self.assertEqual(("RUN", "A"), hold.call_args.args[:2])


class TestHeldComposition(FrappeTestCase):
	def test_a_held_composition_fails_its_attempt_so_the_task_stays_failed(self):
		orchestrator = generation_orchestrator
		with (
			patch("frappe.get_all", side_effect=[["TASK"], ["ATT"]]),
			patch("frappe.db.set_value") as set_value,
			patch("frappe.get_doc", return_value=frappe._dict(name="TASK")),
			patch.object(orchestrator, "_update_job_summary") as summary,
			patch("frappe.db.commit"),
		):
			orchestrator._hold_composition("RUN", "SHOT", ValueError("tracking ambiguous"))
		doctype, name, values = set_value.call_args.args[:3]
		self.assertEqual(
			("Generation Attempt", "ATT", "Failed", "Input"),
			(doctype, name, values["status"], values["failure_class"]),
		)
		summary.assert_called_once()
