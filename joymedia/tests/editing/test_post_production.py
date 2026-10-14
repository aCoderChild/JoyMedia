from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.editing import post_production as post_production


class TestSegmentedSoundtrack(FrappeTestCase):
	@patch("joymedia.services.editing.post_production._video_workflow")
	def test_soundtrack_uses_the_project_workflow_contract(self, video_workflow):
		video_workflow.return_value = ({"save": {"inputs": {}}}, "save")

		workflow, output_node = post_production._soundtrack_workflow("PROJECT-TEST", "first.png", "soft piano", 31)

		self.assertEqual("save", output_node)
		self.assertIn("save", workflow)
		args = video_workflow.call_args.args
		self.assertEqual(("PROJECT-TEST", "first.png"), args[:2])
		self.assertIn("soft piano", args[2])


class TestPostProductionStatus(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.project = frappe.get_doc({
			"doctype": "Media Project",
			"project_name": "Test Finishing Project",
			"product_name": "Test Product",
			"total_duration_seconds": 10,
			"delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	@patch("joymedia.services.editing.post_production.frappe.db.commit")
	@patch("joymedia.services.editing.post_production.is_render_alive", return_value=False)
	def test_finishing_whose_job_died_is_reported_failed(self, alive, commit):
		self.project.db_set("post_production_status", "Running")

		status = post_production.get_post_production_status(self.project.name)

		self.assertEqual("Failed", status["status"])
		self.assertTrue(status["error"])

	@patch("joymedia.services.editing.post_production.frappe.db.commit")
	@patch("joymedia.services.editing.post_production._require_approved_shots")
	@patch("joymedia.services.editing.post_production._shot_video_clips", return_value=[frappe._dict(name="CLIP-1")])
	@patch("joymedia.services.editing.post_production.now_datetime", return_value=datetime(2026, 10, 12, 9, 0, 0))
	@patch("joymedia.services.editing.post_production.is_render_alive", return_value=True)
	def test_running_finishing_records_refresh_without_queueing_twice(self, alive, now, clips, approved, commit):
		self.project.db_set("post_production_status", "Running")

		with patch("joymedia.services.editing.post_production.enqueue_render") as enqueue:
			self.assertEqual({"status": "Running"}, post_production.queue_post_production_internal(self.project.name))
		enqueue.assert_not_called()
		self.assertEqual(
			datetime(2026, 10, 12, 9, 0, 0),
			frappe.db.get_value("Media Project", self.project.name, "post_production_requested_at"),
		)

	@patch("joymedia.services.editing.post_production._finishing_is_current", return_value=True)
	@patch("joymedia.services.editing.post_production._unapproved_shots", return_value=[])
	@patch("joymedia.services.editing.post_production._shot_video_clips", return_value=[frappe._dict(name="CLIP-1")])
	@patch("joymedia.services.editing.post_production.queue_post_production_internal")
	def test_unchanged_approved_project_does_not_refinish(self, queue, clips, unapproved, current):
		self.assertEqual({"status": "Completed"}, post_production.resume_post_production_if_approved(self.project.name))
		queue.assert_not_called()

	@patch("joymedia.services.editing.post_production.frappe.db.commit")
	def test_finishing_repeats_when_a_scene_changes_while_it_runs(self, commit):
		from frappe.utils import now_datetime

		rounds = []

		def finish_once(project_name):
			rounds.append(project_name)
			if len(rounds) == 1:  # a scene is regenerated during the first pass
				frappe.db.set_value(
					"Media Project", project_name, "post_production_requested_at", now_datetime()
				)

		with patch("joymedia.services.editing.post_production._finish_once", side_effect=finish_once):
			post_production.run_post_production(self.project.name)

		self.assertEqual(2, len(rounds))
		self.assertEqual("Completed", frappe.db.get_value("Media Project", self.project.name, "post_production_status"))

	@patch("joymedia.services.editing.post_production._selected_outputs_are_incorporated", return_value=True)
	@patch("joymedia.services.editing.post_production.frappe.db.commit")
	def test_finishing_stays_queued_when_the_final_allowed_round_is_stale(self, commit, incorporated):
		started = datetime(2026, 10, 12, 9, 0, 0)
		rounds = []

		def finish_once(project_name):
			rounds.append(project_name)
			# Every pass receives a newer request, including the third and final pass.
			frappe.db.set_value(
				"Media Project", project_name, "post_production_requested_at",
				datetime(2026, 10, 12, 9, 1, 0),
			)

		with patch("joymedia.services.editing.post_production.now_datetime", return_value=started), patch(
			"joymedia.services.editing.post_production._finish_once", side_effect=finish_once
		):
			post_production.run_post_production(self.project.name)

		self.assertEqual(post_production.MAX_FINISHING_ROUNDS, len(rounds))
		self.assertEqual("Queued", frappe.db.get_value("Media Project", self.project.name, "post_production_status"))

	@patch("joymedia.services.editing.post_production._finishing_is_current", return_value=False)
	@patch("joymedia.services.editing.post_production._unapproved_shots", return_value=[])
	@patch("joymedia.services.editing.post_production.is_render_alive", return_value=False)
	@patch("joymedia.services.editing.post_production.queue_post_production_internal")
	def test_scheduler_requeues_a_persisted_request_without_a_live_job(self, queue, alive, unapproved, current):
		self.project.db_set({
			"post_production_status": "Queued",
			"post_production_requested_at": datetime(2026, 10, 12, 9, 0, 0),
		})

		post_production.resume_queued_post_productions()

		queue.assert_called_once_with(self.project.name)


class TestMusicEnding(FrappeTestCase):
	def test_film_ends_on_the_quietest_moment_of_the_music(self):
		import subprocess
		import tempfile
		from pathlib import Path

		with tempfile.TemporaryDirectory() as temp_dir:
			audio = Path(temp_dir) / "music.wav"
			# 14 s of tone with a pause at 11.3-11.7 s; the film is 10 s long.
			subprocess.run(
				["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=14",
				 "-af", "volume='if(between(t,11.3,11.7),0.02,1)':eval=frame", str(audio)],
				check=True,
			)

			start = post_production._music_start_frame(audio, 240)

		self.assertAlmostEqual(36, start, delta=3)


class TestEditedTimelineIsKept(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc(
			{"doctype": "Media Project", "project_name": "Edited Timeline", "delivery_preset": "Landscape"}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _finish(self, signature):
		with patch("joymedia.services.editing.post_production.timeline_signature", return_value=signature), patch(
			"joymedia.services.editing.post_production._finish_once"
		) as full, patch("joymedia.services.editing.post_production._patch_changed_scenes") as patch_scenes:
			post_production.run_post_production(self.project.name)
		return full.called, patch_scenes.called

	def test_untouched_timeline_is_rebuilt_and_remembered(self):
		self.assertEqual((True, False), self._finish("state-a"))
		self.assertEqual("state-a", frappe.db.get_value("Media Project", self.project.name, "finished_timeline_signature"))
		# Nothing edited since: the next refinish rebuilds again.
		self.assertEqual((True, False), self._finish("state-a"))

	def test_timeline_edited_by_hand_is_patched_not_rebuilt(self):
		self._finish("state-a")

		self.assertEqual((False, True), self._finish("state-edited"))

	@patch("joymedia.services.editing.post_production.queue_post_production_internal")
	def test_redo_button_rebuilds_even_an_edited_timeline(self, queue):
		self.project.db_set("finished_timeline_signature", "state-a")

		post_production.queue_post_production(self.project.name)

		self.assertFalse(frappe.db.get_value("Media Project", self.project.name, "finished_timeline_signature"))
		queue.assert_called_once()
