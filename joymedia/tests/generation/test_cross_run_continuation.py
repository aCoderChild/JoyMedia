"""Real-database test: an independently regenerated Continue shot can be created and validated."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation import takes as scene_takes
from joymedia.tests.editing.test_timeline import _create_output_version, _create_workflow
from joymedia.tests.support.e2e_setup import _generate_image_bytes


class TestCrossRunContinuation(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		# Keep the test independent of whichever pipeline the site has promoted.
		no_pipeline = patch(
			"joymedia.services.workflows.pipeline.get_active_generation_pipeline",
			side_effect=frappe.ValidationError("No active Generation Pipeline is configured."),
		)
		no_pipeline.start()
		self.addCleanup(no_pipeline.stop)
		self.workflow = _create_workflow()
		self.project = frappe.get_doc({
			"doctype": "Media Project", "project_name": "Cross Run", "workflow": self.workflow,
			"total_duration_seconds": 4, "delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)
		self.shot1 = self._shot(1, "New Scene")
		self.shot2 = self._shot(2, "Continue")
		self.original_run = self._run({})
		self.original_task = self._task(self.original_run, self.shot1)
		self._complete_with_approved_output(self.original_task, self.shot1)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _shot(self, number, mode):
		return frappe.get_doc({
			"doctype": "Shot", "media_project": self.project.name, "shot_number": number, "continuity_mode": mode,
			"generation_prompt": f"Scene {number}.", "duration_seconds": 2.0, "planned_frame_count": 48,
		}).insert(ignore_permissions=True)

	def _run(self, scope):
		from joymedia.services.project.context import build_project_snapshot

		snapshot_json, snapshot_hash = build_project_snapshot(frappe.get_doc("Media Project", self.project.name))
		return frappe.get_doc({
			"doctype": "Generation Run", "media_project": self.project.name, "workflow": self.workflow,
			"project_snapshot_json": snapshot_json, "project_snapshot_hash": snapshot_hash,
			"execution_scope_json": json.dumps(scope),
			"requested_by": "Administrator", "status": "Draft",
		}).insert(ignore_permissions=True)

	def _task(self, run, shot, depends_on=None):
		task = frappe.get_doc({
			"doctype": "Generation Task",
			"inputs": [] if depends_on else [{"input_role": "first_frame", "asset_version": self._image_version()}], "generation_run": run.name, "shot": shot.name, "workflow": self.workflow,
			"prompt_text": shot.generation_prompt, "prompt_hash": "h", "segment_index": 1, "segment_frame_count": 48,
			"segment_start_frame": 0, "segment_effective_frames": 48, "overlap_frames": 0, "status": "Draft",
			"depends_on_task": depends_on, "dependency_artifact_role": "Last Frame" if depends_on else None,
		})
		return task.insert(ignore_permissions=True)

	def _image_version(self):
		asset = frappe.get_doc({
			"doctype": "Media Asset", "asset_name": f"Frame {frappe.generate_hash(length=4)}", "media_type": "Image",
			"asset_category": "Other", "asset_scope": "Library",
		}).insert(ignore_permissions=True)
		file_doc = frappe.get_doc({
			"doctype": "File", "file_name": "frame.png", "content": _generate_image_bytes(), "is_private": 1,
			"attached_to_doctype": "Media Asset", "attached_to_name": asset.name,
		}).insert(ignore_permissions=True)
		return frappe.get_doc({
			"doctype": "Asset Version", "media_asset": asset.name, "file": file_doc.file_url, "source": "Uploaded",
		}).insert(ignore_permissions=True).name

	def _complete_with_approved_output(self, task, shot, with_last_frame=True):
		task.db_set("status", "Queued")
		attempt = frappe.get_doc({
			"doctype": "Generation Attempt", "generation_task": task.name, "attempt_number": 1, "status": "Completed", "seed": 1,
		}).insert(ignore_permissions=True)
		if with_last_frame:
			file_doc = frappe.get_doc({
				"doctype": "File", "file_name": "last.png", "content": _generate_image_bytes(), "is_private": 1,
			}).insert(ignore_permissions=True)
			frappe.get_doc({
				"doctype": "Generation Artifact", "artifact_key": f"{attempt.name}:last_frame",
				"artifact_role": "Last Frame", "generation_attempt": attempt.name, "media_type": "Image",
				"frappe_file": file_doc.name,
			}).insert(ignore_permissions=True)
		task.db_set("status", "Completed")
		_asset, version = _create_output_version(self.project, "take.mp4", 2)
		version.db_set("source_generation_attempt", attempt.name)
		shot.db_set({"selected_output_asset_version": version.name})

	def test_regeneration_task_validates_against_the_selected_predecessor(self):
		source = scene_takes._continuation_source_task(self.project, [self.shot2.name])
		self.assertEqual(self.original_task.name, source)

		regen_run = self._run({"shot_names": [self.shot2.name], "continuation_from_task": source})
		task = self._task(regen_run, self.shot2, depends_on=source)

		self.assertEqual(source, task.depends_on_task)

	def test_dependency_without_scope_authorization_is_rejected(self):
		other_run = self._run({"shot_names": [self.shot2.name]})
		with self.assertRaises(frappe.ValidationError):
			self._task(other_run, self.shot2, depends_on=self.original_task.name)

	def test_dependency_whose_output_is_no_longer_selected_is_rejected(self):
		_asset, other = _create_output_version(self.project, "other.mp4", 2)
		self.shot1.db_set("selected_output_asset_version", other.name)
		run = self._run({"continuation_from_task": self.original_task.name})
		with self.assertRaises(frappe.ValidationError):
			self._task(run, self.shot2, depends_on=self.original_task.name)

	def test_a_predecessor_without_an_output_blocks_regeneration(self):
		self.shot1.db_set("selected_output_asset_version", None)
		with self.assertRaises(frappe.ValidationError):
			scene_takes._continuation_source_task(self.project, [self.shot2.name])


	def test_a_submission_cut_short_becomes_submittable_again(self):
		"""A restart between marking an attempt Submitting and ComfyUI answering must not strand the run."""
		from joymedia.services.generation.runner import reconcile_attempt_submission

		task = self._task(self._run({}), self.shot2)
		task.db_set("status", "Queued")
		attempt = frappe.get_doc({
			"doctype": "Generation Attempt", "generation_task": task.name, "attempt_number": 1, "status": "Pending", "seed": 1,
		}).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Generation Attempt", attempt.name,
			{"status": "Submitting", "submission_state": "Submitting", "submission_token": f"joymedia:{attempt.name}",
			 "comfyui_endpoint_url": "http://127.0.0.1:8188", "modified": frappe.utils.add_to_date(None, minutes=-10)},
			update_modified=False,
		)
		with patch("joymedia.services.generation.runner.find_prompt_by_client_id", return_value=None):
			result = reconcile_attempt_submission(attempt.name)

		self.assertTrue(result["retryable"])
		attempt.reload()
		self.assertEqual(("Pending", "Not Submitted"), (attempt.status, attempt.submission_state))

	def test_retrying_a_task_revives_only_the_dependents_its_failure_cancelled(self):
		from joymedia.services.generation.ingestor import CASCADE_CANCEL_SUMMARY
		from joymedia.services.generation.orchestrator import _revive_cancelled_dependents

		run = self._run({})
		parent = self._task(run, self.shot1)
		cascaded = self._task(run, self.shot2, depends_on=parent.name)
		cascaded.db_set({"status": "Cancelled", "error_summary": CASCADE_CANCEL_SUMMARY})
		other_shot = self._shot(3, "New Scene")
		by_hand = self._task(run, other_shot, depends_on=parent.name)
		by_hand.db_set({"status": "Cancelled", "error_summary": "Cancelled by the user."})

		revived = _revive_cancelled_dependents(parent.name)

		self.assertEqual([cascaded.name], revived)
		self.assertEqual("Ready", frappe.db.get_value("Generation Task", cascaded.name, "status"))
		self.assertEqual("Cancelled", frappe.db.get_value("Generation Task", by_hand.name, "status"))
