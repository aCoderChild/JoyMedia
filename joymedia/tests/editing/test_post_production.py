from datetime import datetime
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.editing import music
from joymedia.services.editing import post_production as post_production


class TestSegmentedSoundtrack(FrappeTestCase):
	@patch("joymedia.services.editing.music._video_workflow")
	def test_soundtrack_uses_the_project_workflow_contract(self, video_workflow):
		video_workflow.return_value = ({"save": {"inputs": {}}}, "save")

		workflow, output_node = post_production._soundtrack_workflow(
			"PROJECT-TEST", "first.png", "soft piano", 31
		)

		self.assertEqual("save", output_node)
		self.assertIn("save", workflow)
		args = video_workflow.call_args.args
		self.assertEqual(("PROJECT-TEST", "first.png"), args[:2])
		self.assertIn("soft piano", args[2])


class TestPostProductionStatus(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Test Finishing Project",
				"product_name": "Test Product",
				"total_duration_seconds": 10,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	@patch("joymedia.services.editing.post_production._selected_outputs_are_incorporated", return_value=True)
	def test_a_take_made_after_the_last_finishing_has_not_been_finished(self, incorporated):
		self.project.db_set(
			{
				"post_production_status": "Completed",
				"post_production_requested_at": datetime(2026, 10, 12, 9, 0, 0),
			}
		)
		with patch.object(
			post_production, "_newest_take_time", return_value=datetime(2026, 10, 12, 10, 0, 0)
		):
			# On the timeline already (the composer puts a new take there), but not finished.
			self.assertFalse(post_production._finishing_is_current(self.project.name))
		with patch.object(post_production, "_newest_take_time", return_value=datetime(2026, 10, 12, 8, 0, 0)):
			self.assertTrue(post_production._finishing_is_current(self.project.name))

	@patch("joymedia.services.editing.post_production.frappe.db.commit")
	@patch("joymedia.services.editing.post_production.is_render_alive", return_value=False)
	def test_finishing_whose_job_died_is_reported_failed(self, alive, commit):
		self.project.db_set("post_production_status", "Running")

		status = post_production.get_post_production_status(self.project.name)

		self.assertEqual("Failed", status["status"])
		self.assertTrue(status["error"])

	@patch("joymedia.services.editing.post_production.frappe.db.commit")
	@patch(
		"joymedia.services.editing.post_production._shot_video_clips",
		return_value=[frappe._dict(name="CLIP-1")],
	)
	@patch(
		"joymedia.services.editing.post_production.now_datetime", return_value=datetime(2026, 10, 12, 9, 0, 0)
	)
	@patch("joymedia.services.editing.post_production.is_render_alive", return_value=True)
	def test_running_finishing_records_refresh_without_queueing_twice(self, alive, now, clips, commit):
		self.project.db_set("post_production_status", "Running")

		with patch("joymedia.services.editing.post_production.enqueue_render") as enqueue:
			self.assertEqual(
				{"status": "Running"}, post_production.queue_post_production_internal(self.project.name)
			)
		enqueue.assert_not_called()
		self.assertEqual(
			datetime(2026, 10, 12, 9, 0, 0),
			frappe.db.get_value("Media Project", self.project.name, "post_production_requested_at"),
		)

	@patch("joymedia.services.editing.post_production._finishing_is_current", return_value=True)
	@patch(
		"joymedia.services.editing.post_production._shot_video_clips",
		return_value=[frappe._dict(name="CLIP-1")],
	)
	@patch("joymedia.services.editing.post_production.queue_post_production_internal")
	def test_an_unchanged_film_is_not_rebuilt(self, queue, clips, current):
		self.assertEqual({"status": "Completed"}, post_production.resume_post_production(self.project.name))
		queue.assert_not_called()

	def test_partial_take_selection_does_not_finish_or_shorten_the_film(self):
		with (
			patch.object(
				frappe,
				"get_all",
				return_value=[
					frappe._dict(selected_output_asset_version="reviewed_take"),
					frappe._dict(selected_output_asset_version=None),
				],
			),
			patch.object(post_production, "_shot_video_clips") as clips,
			patch.object(post_production, "queue_post_production_internal") as queue,
		):
			self.assertEqual(
				{"status": "Awaiting Scenes"}, post_production.resume_post_production(self.project.name)
			)
		clips.assert_not_called()
		queue.assert_not_called()
		self.assertEqual(
			10, frappe.db.get_value("Media Project", self.project.name, "total_duration_seconds")
		)

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
		self.assertEqual(
			"Completed", frappe.db.get_value("Media Project", self.project.name, "post_production_status")
		)

	@patch("joymedia.services.editing.post_production._selected_outputs_are_incorporated", return_value=True)
	@patch("joymedia.services.editing.post_production.frappe.db.commit")
	def test_finishing_stays_queued_when_the_final_allowed_round_is_stale(self, commit, incorporated):
		started = datetime(2026, 10, 12, 9, 0, 0)
		rounds = []

		def finish_once(project_name):
			rounds.append(project_name)
			# Every pass receives a newer request, including the third and final pass.
			frappe.db.set_value(
				"Media Project",
				project_name,
				"post_production_requested_at",
				datetime(2026, 10, 12, 9, 1, 0),
			)

		with (
			patch("joymedia.services.editing.post_production.now_datetime", return_value=started),
			patch("joymedia.services.editing.post_production._finish_once", side_effect=finish_once),
		):
			post_production.run_post_production(self.project.name)

		self.assertEqual(post_production.MAX_FINISHING_ROUNDS, len(rounds))
		self.assertEqual(
			"Queued", frappe.db.get_value("Media Project", self.project.name, "post_production_status")
		)

	@patch("joymedia.services.editing.post_production._finishing_is_current", return_value=False)
	@patch("joymedia.services.editing.post_production.is_render_alive", return_value=False)
	@patch("joymedia.services.editing.post_production.queue_post_production_internal")
	def test_scheduler_requeues_a_persisted_request_without_a_live_job(self, queue, alive, current):
		self.project.db_set(
			{
				"post_production_status": "Queued",
				"post_production_requested_at": datetime(2026, 10, 12, 9, 0, 0),
			}
		)

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
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-f",
					"lavfi",
					"-i",
					"sine=frequency=330:duration=14",
					"-af",
					"volume='if(between(t,11.3,11.7),0.02,1)':eval=frame",
					str(audio),
				],
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
		with (
			patch("joymedia.services.editing.post_production.timeline_signature", return_value=signature),
			patch("joymedia.services.editing.post_production._finish_once") as full,
			patch("joymedia.services.editing.post_production._patch_changed_scenes") as patch_scenes,
		):
			post_production.run_post_production(self.project.name)
		return full.called, patch_scenes.called

	def test_untouched_timeline_is_rebuilt_and_remembered(self):
		self.assertEqual((True, False), self._finish("state-a"))
		self.assertEqual(
			"state-a", frappe.db.get_value("Media Project", self.project.name, "finished_timeline_signature")
		)
		# Nothing edited since: the next refinish rebuilds again.
		self.assertEqual((True, False), self._finish("state-a"))

	def test_timeline_edited_by_hand_is_patched_not_rebuilt(self):
		self._finish("state-a")

		self.assertEqual((False, True), self._finish("state-edited"))

	@patch("joymedia.services.editing.post_production.queue_post_production_internal")
	def test_redo_button_rebuilds_even_an_edited_timeline(self, queue):
		self.project.db_set("finished_timeline_signature", "state-a")

		post_production.queue_post_production(self.project.name)

		self.assertFalse(
			frappe.db.get_value("Media Project", self.project.name, "finished_timeline_signature")
		)
		queue.assert_called_once()


class TestFinishingFollowsTheSoundMode(FrappeTestCase):
	def _finish(self, soundtrack_mode):
		values = {"generation_mode": "Continuous", "soundtrack_mode": soundtrack_mode}
		with (
			patch("joymedia.services.editing.timeline.reset_project_timeline"),
			patch("joymedia.services.editing.timeline.close_timeline_gaps") as close_gaps,
			patch.object(post_production, "_shot_video_clips", return_value=[]),
			patch.object(post_production, "_set_status"),
			patch.object(post_production, "_add_soundtrack") as add_soundtrack,
			patch("joymedia.services.audio.plan.check_scene_audio") as screen,
			patch("joymedia.services.audio.plan.use_separate_effects_layer") as layers,
			patch.object(
				post_production.frappe.db, "get_value", side_effect=lambda doctype, name, field: values[field]
			),
		):
			post_production._finish_once("P")
		close_gaps.assert_called_once_with("P")  # scenes cut directly into each other
		return add_soundtrack, screen, layers

	def test_a_full_soundtrack_film_gets_generated_music_and_no_screen(self):
		music, screen, layers = self._finish("Full soundtrack")
		music.assert_called_once()
		screen.assert_not_called()
		layers.assert_not_called()

	def test_sound_effects_only_screens_the_scenes_audio_and_adds_no_music(self):
		music, screen, layers = self._finish("Sound effects only")
		music.assert_not_called()
		screen.assert_called_once_with("P")
		layers.assert_not_called()

	def test_a_separate_effects_layer_is_generated_for_every_scene(self):
		music, screen, layers = self._finish("Separate effects layer")
		music.assert_not_called()
		layers.assert_called_once_with("P")
		screen.assert_not_called()


class TestMusicBed(FrappeTestCase):
	def test_long_score_uses_declared_capacity_and_short_workflow_keeps_loop_fallback(self):
		from unittest.mock import MagicMock

		for maximum, expected in ((744, 744), (192, 192)):
			workflow = frappe._dict(execution_spec={"limits": {"max_frames": maximum}})
			adapter = MagicMock()
			adapter.extract_execution_metadata.return_value = {"primary_output_node_key": "save"}
			with (
				patch.object(frappe, "get_doc", return_value=workflow),
				patch(
					"joymedia.services.workflows.resolver.build_execution_workflow", return_value={"save": {}}
				) as build,
				patch("joymedia.workflow_adapters.get_workflow_adapter", return_value=adapter),
				patch("joymedia.services.workflows.comfyui.run_workflow_to_bytes", return_value=b"audio"),
				patch.object(music, "music_bed"),
				patch.object(music, "_save_output", return_value="NEW-MUSIC"),
				patch("pathlib.Path.read_bytes", return_value=b"audio"),
			):
				self.assertEqual(
					"NEW-MUSIC",
					post_production._render_workflow_music_bed("P", "Music", "WF", "bright funk", 720),
				)
			self.assertEqual(expected, build.call_args.kwargs["frame_count"])
			prompt = build.call_args.kwargs["inputs"]["generation_prompt"]
			self.assertIn("continuous" if maximum == 744 else "loopable", prompt)

	def test_music_refresh_preserves_picture_and_narration(self):
		with (
			patch.object(post_production, "_add_music_bed") as music,
			patch.object(post_production, "_set_status"),
			patch.object(post_production.frappe.db, "set_value"),
			patch("joymedia.services.editing.timeline._invalidate_project_output") as invalidate,
			patch.object(post_production, "_finish_once") as rebuild,
		):
			post_production.run_music_bed("P")
		music.assert_called_once_with("P")
		invalidate.assert_called_once_with("P")
		rebuild.assert_not_called()

	def test_a_short_music_clip_is_looped_with_crossfades_to_the_films_length(self):
		import subprocess
		import tempfile
		from pathlib import Path

		with tempfile.TemporaryDirectory() as folder:
			clip = Path(folder) / "clip.mp4"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-f",
					"lavfi",
					"-i",
					"anoisesrc=color=pink:duration=10:amplitude=0.3",
					"-c:a",
					"aac",
					str(clip),
				],
				check=True,
			)
			bed = post_production.music_bed(clip, 36.0, Path(folder) / "bed.m4a")
			duration = float(
				subprocess.run(
					[
						"ffprobe",
						"-v",
						"error",
						"-show_entries",
						"format=duration",
						"-of",
						"csv=p=0",
						str(bed),
					],
					capture_output=True,
					text=True,
					check=True,
				).stdout
			)
			# No silence where a copy ends: the loudest drop over the bed stays small.
			levels = subprocess.run(
				[
					"ffmpeg",
					"-i",
					str(bed),
					"-af",
					"astats=metadata=1:reset=24,ametadata=print:key=lavfi.astats.Overall.RMS_level",
					"-f",
					"null",
					"-",
				],
				capture_output=True,
				text=True,
			).stderr
		self.assertAlmostEqual(36.0, duration, delta=0.1)
		rms = [
			float(v) for v in __import__("re").findall(r"RMS_level=(-?[\d.]+)", levels) if v not in ("-inf",)
		]
		self.assertGreater(min(rms[2:-2]), max(rms) - 9)

	def test_the_music_follows_the_projects_own_text_else_the_sheets_mood_and_bgm_notes(self):
		project = frappe._dict(soundtrack_prompt="", name="PRJ-X")
		with (
			patch.object(frappe, "get_doc", return_value=project),
			patch.object(
				frappe,
				"get_all",
				return_value=["SFX: a cup falls\nBGM: Dồn dập, kịch tính rồi dừng ngắt", "SFX: pop"],
			),
			patch(
				"joymedia.services.planning.prompts.sheet_brief",
				return_value={"tone": "Cute, warm and playful", "usp": "", "characters": {}},
			),
		):
			self.assertEqual(
				"light instrumental background music for a Cute, warm and playful advertisement, in the spirit of: Dồn dập, kịch tính rồi dừng ngắt",
				post_production.music_brief("PRJ-X"),
			)
		project.soundtrack_prompt = "soft ukulele"
		with patch.object(frappe, "get_doc", return_value=project):
			self.assertEqual("soft ukulele", post_production.music_brief("PRJ-X"))


class TestFinishingCancellation(TestCase):
	def test_late_worker_cannot_revive_cancelled_finishing(self):
		with (
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
			patch.object(frappe.db, "get_value", return_value="Cancelled"),
			patch.object(frappe.db, "set_value") as write,
		):
			for status in ["Running", "Completed"]:
				with self.assertRaisesRegex(ValueError, "cancelled"):
					post_production._set_status("PROJECT", status)
		write.assert_not_called()


class TestFinishingWriteRetry(TestCase):
	def test_explicit_rebuild_request_retries_write_before_queueing_once(self):
		project = Mock()
		project.name = "PROJECT"
		with (
			patch.object(frappe, "get_doc", return_value=project),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback") as rollback,
			patch.object(
				frappe.db, "set_value", side_effect=[frappe.QueryDeadlockError("row changed"), None]
			) as write,
			patch.object(
				post_production, "queue_post_production_internal", return_value={"status": "Queued"}
			) as queue,
		):
			self.assertEqual({"status": "Queued"}, post_production.queue_post_production("PROJECT"))
		self.assertEqual(2, write.call_count)
		rollback.assert_called_once()
		queue.assert_called_once_with("PROJECT")

	def test_request_timestamp_retry_does_not_enqueue_duplicate_live_finish(self):
		with (
			patch.object(post_production, "_shot_video_clips", return_value=[{}]),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback") as rollback,
			patch.object(
				frappe.db, "set_value", side_effect=[frappe.QueryDeadlockError("row changed"), None]
			) as write,
			patch.object(frappe.db, "get_value", return_value="Running"),
			patch.object(post_production, "is_render_alive", return_value=True),
			patch.object(post_production, "enqueue_render") as enqueue,
		):
			self.assertEqual({"status": "Running"}, post_production.queue_post_production_internal("PROJECT"))
		self.assertEqual(write.call_args_list[0], write.call_args_list[1])
		rollback.assert_called_once()
		enqueue.assert_not_called()
