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


class TestAudioDirection(FrappeTestCase):
	def test_effects_and_music_become_the_h3_audio_line_and_narration_is_left_out(self):
		beat = {"audio": "SFX: Tiếng cốc đổ\nBGM: Nhạc vui nhộn\nGhi chú"}
		with patch.object(planner, "translate", side_effect=lambda text, project: {"Tiếng cốc đổ": "a glass tipping", "Nhạc vui nhộn": "playful music"}[text]):
			line = planner.audio_direction(frappe._dict(), beat)
		self.assertEqual("Audio: sound effects: a glass tipping; music: playful music.", line)

	def test_a_beat_without_sound_direction_adds_nothing(self):
		self.assertEqual("", planner.audio_direction(frappe._dict(), {"audio": ""}))
		self.assertEqual("", planner.audio_direction(frappe._dict(), {}))


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

	def test_the_scenes_sound_direction_survives_planning(self):
		plan = {**planner.normalize_production_shot(RAW, reference_keys=set(), duration=3.0, is_first=True), "audio": "Audio: sound effects: a pop."}
		planner.apply_production_shot(self.project, self.shot, plan)
		prompt = frappe.get_doc("Shot", self.shot.name).generation_prompt
		self.assertTrue(prompt.startswith(RAW["video_prompt"]))
		self.assertTrue(prompt.endswith("Audio: sound effects: a pop."))

	def test_a_planner_answer_in_the_beats_language_is_translated(self):
		beat = {"summary": "Mother bear spills the milk.", "camera": "", "action": "", "audio": "", "voice_over": "", "on_screen_text": "", "raw": "x"}
		raw = {**RAW, "video_prompt": "Gấu mẹ đánh đổ cốc sữa."}
		with patch.object(planner, "_ask_planner", return_value=raw), patch.object(planner, "creative_beat", return_value=beat), patch.object(
			planner, "beat_coverage", return_value=(0.9, [])
		), patch.object(planner, "ground_reference_keys", return_value=([], [])), patch.object(
			planner, "translate", side_effect=lambda text, project: "Mother bear spills the milk." if not str(text).isascii() else text
		):
			plan = planner.plan_production_shot(self.project, self.shot, references=[])
		self.assertEqual("Mother bear spills the milk.", plan["video_prompt"])

	def test_motion_only_asks_for_movement_and_not_for_place_or_light(self):
		with patch.object(planner, "_ask_planner", return_value={"motion": "  The mother lifts a tissue. "}) as ask:
			result = planner.motion_only(self.project, "Candlelight. Mother lifts a tissue.", [{"label": "Mama", "role": "Character"}])
		self.assertEqual("The mother lifts a tissue.", result)
		self.assertIn("ONLY what moves", ask.call_args.args[0])
		self.assertIn("Mama", ask.call_args.args[0])

	def test_the_planners_foley_is_used_when_the_beat_names_no_sound(self):
		project = frappe._dict(selected_media=[], product_name="P", project_name="P")
		self.assertEqual(
			"Audio: sound effects: soft tissue rustling.",
			planner.audio_direction(project, {"audio": ""}, "soft tissue rustling."),
		)
		self.assertEqual("", planner.audio_direction(project, {"audio": ""}))

	def test_a_plan_that_drops_the_beat_falls_back_to_the_beats_english_wording(self):
		beat = {"summary": "Mother bear spills the milk.", "camera": "", "action": "", "audio": "", "voice_over": "", "on_screen_text": "", "raw": "x"}
		with patch.object(planner, "_ask_planner", return_value=RAW), patch.object(
			planner, "creative_beat", return_value=beat
		), patch.object(planner, "beat_coverage", return_value=(0.1, ["milk"])), patch.object(
			planner, "ground_reference_keys", return_value=([], [])
		), patch.object(planner, "motion_only", return_value="Mother bear spills the milk."):
			plan = planner.plan_production_shot(self.project, self.shot, references=[])
		self.assertEqual("Mother bear spills the milk.", plan["video_prompt"])
		self.assertEqual(1, len(plan["motion_plan"]["actions"]))
		self.assertFalse(plan["held_back"])

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
		# Progress must not wait for the job's final commit, or it all arrives in one burst at the end.
		self.assertTrue(all(c.kwargs["after_commit"] is False for c in publish.call_args_list))

	def test_a_failed_job_tells_the_studio_why(self):
		from joymedia.api import storyboard

		with patch.object(storyboard, "_plan_project", side_effect=frappe.ValidationError("planner down")), patch(
			"joymedia.services.realtime.frappe.publish_realtime"
		) as publish, self.assertRaises(frappe.ValidationError):
			storyboard.run_planning_job(self.project.name, None, "Administrator")
		last = publish.call_args_list[-1].args[1]
		self.assertEqual("failed", last["state"])
		self.assertIn("planner down", last["error"])


class TestGrounding(FrappeTestCase):
	REFS = [
		{"key": "mascot", "label": "Gau Shera mascot", "role": "Character"},
		{"key": "pack", "label": "Shera pack", "role": "Product"},
	]
	PROJECT = frappe._dict(product_name="Khăn giấy rút cao cấp Shera", project_name="P")

	def test_a_beat_that_names_the_product_gets_its_reference_even_if_the_planner_missed_it(self):
		beat = {"raw": "Gấu con rút từng tờ giấy Shera ra khỏi bịch", "camera": "", "action": "The cub pulls tissue"}
		keys, notes = planner.ground_reference_keys(self.PROJECT, beat, ["mascot"], self.REFS)
		self.assertEqual(["mascot", "pack"], keys)
		self.assertTrue(notes)

	def test_a_beat_about_something_else_is_left_alone(self):
		beat = {"raw": "Cảnh toàn thành phố lúc hoàng hôn", "camera": "", "action": "A city at dusk"}
		self.assertEqual((["mascot"], []), planner.ground_reference_keys(self.PROJECT, beat, ["mascot"], self.REFS))

	def test_the_characters_own_name_does_not_count_as_mentioning_the_product(self):
		# 'Shera' is also in the mascot's label, so it must not pull the pack into every scene by itself.
		beat = {"raw": "Gấu mẹ Shera nhảy múa", "camera": "", "action": "Mother Shera bear dances"}
		keys, _ = planner.ground_reference_keys(self.PROJECT, beat, ["mascot"], self.REFS)
		self.assertEqual(["mascot"], keys)

	def test_an_already_chosen_product_is_not_duplicated(self):
		beat = {"raw": "giấy Shera", "camera": "", "action": ""}
		self.assertEqual((["pack"], []), planner.ground_reference_keys(self.PROJECT, beat, ["pack"], self.REFS))

	def test_a_character_is_added_when_the_beat_uses_a_distinctive_word_of_its_label(self):
		beat = {"raw": "Gấu con hoảng hốt", "camera": "", "action": "The bear cub panics"}
		keys, notes = planner.ground_reference_keys(self.PROJECT, beat, ["pack"], self.REFS)
		self.assertEqual(["pack", "mascot"], keys)
		self.assertTrue(any("mascot" in n.lower() for n in notes))

	def test_identical_planner_requests_are_answered_from_the_cache(self):
		answers = iter([{"n": 1}, {"n": 2}])
		with patch.object(planner, "_request_planner", side_effect=lambda *a, **k: next(answers)) as ask:
			first = planner._ask_planner("same prompt " + frappe.generate_hash(length=6), system="s")
			again = planner._ask_planner("same prompt " + "x", system="s")
		self.assertEqual({"n": 1}, first)
		self.assertEqual(2, ask.call_count)  # different prompts are different requests

	def test_a_repeated_request_is_not_asked_twice_and_refresh_forces_a_new_answer(self):
		prompt = "repeat " + frappe.generate_hash(length=8)
		answers = iter([{"n": 1}, {"n": 2}])
		with patch.object(planner, "_request_planner", side_effect=lambda *a, **k: next(answers)) as ask:
			first = planner._ask_planner(prompt, system="s")
			second = planner._ask_planner(prompt, system="s")
			fresh = planner._ask_planner(prompt, system="s", refresh=True)
		self.assertEqual((first, second), ({"n": 1}, {"n": 1}))
		self.assertEqual({"n": 2}, fresh)
		self.assertEqual(2, ask.call_count)

	def test_the_planner_request_is_reproducible(self):
		self.assertEqual(planner.request_seed("a", "b"), planner.request_seed("a", "b"))
		self.assertNotEqual(planner.request_seed("a", "b"), planner.request_seed("a", "c"))
