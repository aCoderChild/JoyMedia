from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import production_planner as planner
from joymedia.services.test_timeline_editor import _create_workflow

RAW = {
	"image_prompt": "A white bear mascot at a table holding a glass.", "video_prompt": "The bear tips the glass and juice spills.",
	"reference_keys": ["mascot", "ghost"], "continuity_mode": "Continue", "start_state": "bear holds glass",
	"end_state": "juice on table", "motion_plan": {"actions": [{"start": 0, "end": 2, "action": "tips glass"}]},
	"needs_editing": "split-screen of three places",
}


class TestNormalize(FrappeTestCase):
	def _norm(self, raw=None, **kw):
		return planner.normalize_production_shot(
			raw or RAW, reference_keys={"mascot", "pack"}, duration=kw.pop("duration", 3.0), is_first=kw.pop("is_first", False)
		)

	def test_unknown_references_are_dropped_and_reported(self):
		plan = self._norm()
		self.assertEqual(["mascot"], plan["reference_keys"])
		self.assertTrue(any("ghost" in note for note in plan["notes"]))

	def test_first_shot_can_never_continue(self):
		self.assertEqual("New Scene", self._norm(is_first=True)["continuity_mode"])
		self.assertEqual("Continue", self._norm(is_first=False)["continuity_mode"])

	def test_needs_editing_is_surfaced_for_the_reviewer(self):
		self.assertTrue(any(note.startswith("Needs editing") for note in self._norm()["notes"]))

	def test_invalid_motion_timing_is_replaced_not_trusted(self):
		raw = {**RAW, "motion_plan": {"actions": [{"start": 0, "end": 9, "action": "too long"}]}}
		plan = self._norm(raw, duration=3.0)
		self.assertEqual([{"start": 0, "end": 3.0, "action": RAW["video_prompt"]}], plan["motion_plan"]["actions"])

	def test_a_multi_frame_image_prompt_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._norm({**RAW, "image_prompt": "word " * 80})

	def test_missing_prompts_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._norm({**RAW, "video_prompt": ""})


class TestCoverage(FrappeTestCase):
	BEAT = "Mommy bear carries a cup of milk and spills it on a pile of paper. The paper absorbs the milk."

	def test_a_faithful_plan_scores_high(self):
		score, missing = planner.beat_coverage(self.BEAT, "Mommy bear spills milk from a cup onto a pile of paper", "The paper absorbs the milk")
		self.assertGreaterEqual(score, 0.85)
		self.assertTrue({"milk", "pape", "mommy"[:4]}.isdisjoint(missing))

	def test_a_plan_that_drops_the_action_scores_low_and_names_what_is_missing(self):
		score, missing = planner.beat_coverage(self.BEAT, "A hand pulls a tissue from a box")
		self.assertLess(score, planner.MIN_COVERAGE)
		self.assertIn("milk", missing)

	def test_film_vocabulary_is_not_counted_as_content(self):
		self.assertEqual((1.0, []), planner.beat_coverage("Close-up camera angle, soft lighting", "anything"))


class TestApply(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc({
			"doctype": "Media Project", "project_name": "Plan", "workflow": _create_workflow(), "total_duration_seconds": 3,
			"delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)
		self.shot = frappe.get_doc({
			"doctype": "Shot", "media_project": self.project.name, "shot_number": 1, "generation_prompt": "Original.",
			"duration_seconds": 3.0, "caption": "KEEP THIS CLAIM", "voice_over": "Keep this narration", "audio_cues": "SFX: pop",
			"source_timing": "0:00 - 0:03",
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_applying_a_plan_leaves_the_advertisers_copy_and_timing_alone(self):
		plan = planner.normalize_production_shot(RAW, reference_keys=set(), duration=3.0, is_first=True)
		planner.apply_production_shot(self.project, self.shot, plan)

		shot = frappe.get_doc("Shot", self.shot.name)
		self.assertEqual(RAW["image_prompt"], shot.image_prompt)
		self.assertEqual(RAW["video_prompt"], shot.generation_prompt)
		self.assertEqual("New Scene", shot.continuity_mode)
		self.assertIn("Needs editing", shot.planner_notes)
		self.assertEqual(
			("KEEP THIS CLAIM", "Keep this narration", "SFX: pop", "0:00 - 0:03", 3.0),
			(shot.caption, shot.voice_over, shot.audio_cues, shot.source_timing, shot.duration_seconds),
		)

	def test_held_back_plans_are_not_applied_through_the_api(self):
		from joymedia.api import storyboard

		plan = {**planner.normalize_production_shot(RAW, reference_keys=set(), duration=3.0, is_first=True), "held_back": True}
		with patch.object(planner, "plan_production_shot", return_value=plan):
			result = storyboard.plan_project_production(self.project.name)

		self.assertTrue(result[0]["held_back"])
		self.assertEqual("Original.", frappe.get_doc("Shot", self.shot.name).generation_prompt)


class TestRealtimeAndBackgroundPlanning(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc({
			"doctype": "Media Project", "project_name": "Realtime", "workflow": _create_workflow(), "total_duration_seconds": 3,
			"delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_saving_a_project_publishes_to_its_document_room(self):
		with patch("frappe.publish_realtime") as publish:
			self.project.reload()
			self.project.save(ignore_permissions=True)
		events = [call.args[0] for call in publish.call_args_list]
		self.assertIn("joymedia_project_updated", events)
		call = next(c for c in publish.call_args_list if c.args[0] == "joymedia_project_updated")
		self.assertEqual("Media Project", call.kwargs["doctype"])
		self.assertEqual(self.project.name, call.kwargs["docname"])

	def test_planning_is_queued_not_run_in_the_request(self):
		from joymedia.api import storyboard

		with patch("frappe.enqueue") as enqueue:
			result = storyboard.start_project_planning(self.project.name)
		self.assertEqual({"queued": True}, result)
		kwargs = enqueue.call_args.kwargs
		self.assertEqual("long", kwargs["queue"])
		self.assertTrue(kwargs["deduplicate"])
		self.assertEqual(self.project.name, kwargs["project_name"])

	def test_the_job_reports_start_progress_and_completion(self):
		from joymedia.api import storyboard

		def fake_plan(project, wanted, apply, progress=None):
			progress(1, 1, {"shot_name": "Hook", "held_back": False, "notes": []})
			return [{"held_back": False}]

		with patch.object(storyboard, "_plan_project", side_effect=fake_plan), patch(
			"joymedia.services.realtime.frappe.publish_realtime"
		) as publish:
			storyboard.run_planning_job(self.project.name, None, "Administrator")
		states = [c.args[1]["state"] for c in publish.call_args_list]
		self.assertEqual(["started", "running", "done"], states)

	def test_a_failed_job_tells_the_studio_why(self):
		from joymedia.api import storyboard

		with patch.object(storyboard, "_plan_project", side_effect=frappe.ValidationError("planner down")), patch(
			"joymedia.services.realtime.frappe.publish_realtime"
		) as publish, self.assertRaises(frappe.ValidationError):
			storyboard.run_planning_job(self.project.name, None, "Administrator")
		last = publish.call_args_list[-1].args[1]
		self.assertEqual("failed", last["state"])
		self.assertIn("planner down", last["error"])
