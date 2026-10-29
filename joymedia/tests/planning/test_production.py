from typing import ClassVar
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning import production as planner
from joymedia.tests.editing.test_timeline import _create_workflow

RAW = {
	"image_prompt": "A white bear mascot at a table holding a glass.",
	"video_prompt": "The bear tips the glass and juice spills.",
	"reference_keys": ["mascot", "ghost"],
	"continuity_mode": "Continue",
	"start_state": "bear holds glass",
	"end_state": "juice on table",
	"motion_plan": {"actions": [{"start": 0, "end": 2, "action": "tips glass"}]},
	"needs_editing": "split-screen of three places",
}


class TestNormalize(FrappeTestCase):
	def test_named_character_view_keeps_fixed_identity_in_the_shot_planner(self):
		import json

		row = frappe._dict(
			reference_key="mascot", identity_key="mascot", reference_role="Character", asset_version="pose"
		)
		project = frappe._dict(planning_mode="Follow the sheet", selected_media=[row])
		beat = {
			"cast_declared": True,
			"cast": ["mascot"],
			"products": [],
			"camera": "",
			"product_view": "source",
		}
		analysis = {
			"description": "Same character in another pose",
			"identity_appearance": "Cream smooth mascot with two round ears and closed smiling eyes.",
			"qualified_pose_and_support": "seated on the floor",
		}
		plan = {"reference_keys": [], "notes": []}
		with (
			patch.object(planner, "creative_beat", return_value=beat),
			patch("joymedia.services.scene.references.named_reference_views", return_value=["mascot"]),
			patch.object(frappe.db, "get_value", return_value=json.dumps(analysis)),
			patch.object(planner, "follow_the_sheet", return_value=plan) as follow,
			patch.object(planner, "ground_visible_product_keys", return_value=([], [])),
			patch(
				"joymedia.services.planning.product_views.constrain_product_views",
				side_effect=lambda p, plan, **kw: plan,
			),
		):
			planner.plan_production_shot(project, frappe._dict(), references=[{"key": "mascot"}])
		text = follow.call_args.args[3][0]["description"]
		self.assertIn("two round ears", text)
		self.assertIn("closed smiling eyes", text)
		self.assertIn("seated on the floor", text)
		self.assertNotIn("Same character in another pose", text)

	def _norm(self, raw=None, **kw):
		return planner.normalize_production_shot(
			raw or RAW,
			reference_keys={"mascot", "pack"},
			duration=kw.pop("duration", 3.0),
			is_first=kw.pop("is_first", False),
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
		self.assertEqual(
			[{"start": 0, "end": 3.0, "action": RAW["video_prompt"]}], plan["motion_plan"]["actions"]
		)

	def test_a_multi_frame_image_prompt_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._norm({**RAW, "image_prompt": "word " * 80})

	def test_missing_prompts_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._norm({**RAW, "video_prompt": ""})


class TestAudioDirection(FrappeTestCase):
	def test_effects_and_music_become_the_h3_audio_line_and_narration_is_left_out(self):
		beat = {"audio": "SFX: Tiếng cốc đổ\nBGM: Nhạc vui nhộn\nGhi chú"}
		with patch.object(
			planner,
			"translate",
			side_effect=lambda text, project, about="": {
				"Tiếng cốc đổ": "a glass tipping",
				"Nhạc vui nhộn": "playful music",
			}[text],
		):
			full = planner.audio_direction(frappe._dict(soundtrack_mode="Full soundtrack"), beat)
			effects_only = planner.audio_direction(frappe._dict(), beat)  # the default mode
		self.assertEqual("Audio: sound effects: a glass tipping; music: playful music.", full)
		self.assertEqual("Audio: sound effects: a glass tipping.", effects_only)

	def test_a_beat_without_sound_direction_adds_nothing(self):
		self.assertEqual("", planner.audio_direction(frappe._dict(), {"audio": ""}))
		self.assertEqual("", planner.audio_direction(frappe._dict(), {}))


class TestCoverage(FrappeTestCase):
	BEAT = "Mommy bear carries a cup of milk and spills it on a pile of paper. The paper absorbs the milk."

	def test_a_faithful_plan_scores_high(self):
		score, missing = planner.beat_coverage(
			self.BEAT, "Mommy bear spills milk from a cup onto a pile of paper", "The paper absorbs the milk"
		)
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
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Plan",
				"workflow": _create_workflow(),
				"total_duration_seconds": 3,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)
		self.shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"generation_prompt": "Original.",
				"duration_seconds": 3.0,
				"caption": "KEEP THIS CLAIM",
				"voice_over": "Keep this narration",
				"audio_cues": "SFX: pop",
				"source_timing": "0:00 - 0:03",
			}
		).insert(ignore_permissions=True)

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
		plan = {
			**planner.normalize_production_shot(RAW, reference_keys=set(), duration=3.0, is_first=True),
			"audio": "Audio: sound effects: a pop.",
		}
		planner.apply_production_shot(self.project, self.shot, plan)
		prompt = frappe.get_doc("Shot", self.shot.name).generation_prompt
		self.assertTrue(prompt.startswith(RAW["video_prompt"]))
		self.assertTrue(prompt.endswith("Audio: sound effects: a pop."))

	def test_sheet_opening_uses_the_native_frame_binding(self):
		plan = planner.normalize_production_shot(RAW, reference_keys=set(), duration=3.0, is_first=True)
		self.project.append(
			"selected_media",
			{"reference_key": "opening", "label": "Approved cup opening", "asset_version": "VERSION"},
		)
		with (
			patch.object(planner, "creative_beat", return_value={"opening_reference": "opening"}),
			patch("joymedia.api.storyboard.set_project_shot_keyframe") as bind,
		):
			planner.apply_production_shot(self.project, self.shot, plan)
		bind.assert_called_once_with(self.project.name, self.shot.name, "first_frame", "VERSION")

	def test_missing_sheet_opening_stops_planning(self):
		plan = planner.normalize_production_shot(RAW, reference_keys=set(), duration=3.0, is_first=True)
		with (
			patch.object(planner, "creative_beat", return_value={"opening_reference": "missing"}),
			self.assertRaises(frappe.ValidationError),
		):
			planner.apply_production_shot(self.project, self.shot, plan)

	def test_sheet_can_bind_both_boundary_images(self):
		plan = planner.normalize_production_shot(RAW, reference_keys=set(), duration=3.0, is_first=True)
		self.project.append(
			"selected_media", {"reference_key": "pose", "label": "Approved pose", "asset_version": "VERSION"}
		)
		with (
			patch.object(
				planner,
				"creative_beat",
				return_value={"opening_reference": "pose", "ending_reference": "pose"},
			),
			patch("joymedia.api.storyboard.set_project_shot_keyframe") as bind,
		):
			planner.apply_production_shot(self.project, self.shot, plan)
		self.assertEqual(["first_frame", "last_frame"], [call.args[2] for call in bind.call_args_list])

	def test_a_video_prompt_in_the_beats_language_is_replaced_by_the_beats_movements(self):
		beat = {
			"summary": "Mother bear spills the milk.",
			"camera": "",
			"action": "",
			"audio": "",
			"voice_over": "",
			"on_screen_text": "",
			"raw": "x",
		}
		raw = {**RAW, "video_prompt": "Gấu mẹ đánh đổ cốc sữa.: Mother bear spills the milk."}
		with (
			patch.object(planner, "_ask_planner", return_value=raw),
			patch.object(planner, "creative_beat", return_value=beat),
			patch.object(planner, "beat_coverage", return_value=(0.9, [])),
			patch.object(planner, "ground_reference_keys", return_value=([], [])),
			patch.object(planner, "motion_only", return_value="Mother bear spills the milk."),
		):
			plan = planner.plan_production_shot(self.project, self.shot, references=[])
		self.assertEqual("Mother bear spills the milk.", plan["video_prompt"])
		self.assertEqual(1, len(plan["motion_plan"]["actions"]))

	def test_a_translation_that_stays_in_the_original_language_is_retried(self):
		answers = iter([{"english": "Gấu mẹ nháy mắt."}, {"english": "Mother bear winks."}])
		with patch.object(planner, "_ask_planner", side_effect=lambda *a, **k: next(answers)) as ask:
			result = planner.translate("Gấu mẹ nháy mắt.", self.project)
		self.assertEqual("Mother bear winks.", result)
		self.assertEqual(2, ask.call_count)

	def test_motion_only_asks_for_movement_and_not_for_place_or_light(self):
		with patch.object(
			planner, "_ask_planner", return_value={"motion": "  The mother lifts a tissue. "}
		) as ask:
			result = planner.motion_only(
				self.project, "Candlelight. Mother lifts a tissue.", [{"label": "Mama", "role": "Character"}]
			)
		self.assertEqual("The mother lifts a tissue.", result)
		self.assertIn("ONLY what moves", ask.call_args.args[0])
		self.assertIn("Mama", ask.call_args.args[0])
		with patch.object(planner, "_ask_planner", return_value={"motion": "The mother winks."}) as ask:
			planner.motion_only(
				self.project, "x", [], inventory="the mother mascot and 3 small product packs"
			)
		self.assertIn(
			"The characters and products in the scene are exactly: the mother mascot and 3 small product packs",
			ask.call_args.args[0],
		)
		self.assertIn("never turn an object into the advertised product", ask.call_args.args[0])

	def test_the_planners_foley_is_used_when_the_beat_names_no_sound(self):
		project = frappe._dict(selected_media=[], product_name="P", project_name="P")
		self.assertEqual(
			"Audio: sound effects: soft tissue rustling.",
			planner.audio_direction(project, {"audio": ""}, "soft tissue rustling."),
		)
		self.assertEqual("", planner.audio_direction(project, {"audio": ""}))

	def test_a_plan_that_drops_the_beat_falls_back_to_the_beats_english_wording(self):
		beat = {
			"summary": "Mother bear spills the milk.",
			"camera": "",
			"action": "",
			"audio": "",
			"voice_over": "",
			"on_screen_text": "",
			"raw": "x",
		}
		with (
			patch.object(planner, "_ask_planner", return_value=RAW),
			patch.object(planner, "creative_beat", return_value=beat),
			patch.object(planner, "beat_coverage", return_value=(0.1, ["milk"])),
			patch.object(planner, "ground_reference_keys", return_value=([], [])),
			patch.object(planner, "motion_only", return_value="Mother bear spills the milk."),
		):
			plan = planner.plan_production_shot(self.project, self.shot, references=[])
		self.assertEqual("Mother bear spills the milk.", plan["video_prompt"])
		self.assertEqual(1, len(plan["motion_plan"]["actions"]))
		self.assertFalse(plan["held_back"])

	def test_held_back_plans_are_not_applied(self):
		from joymedia.api import storyboard

		plan = {
			**planner.normalize_production_shot(RAW, reference_keys=set(), duration=3.0, is_first=True),
			"held_back": True,
		}
		with patch.object(planner, "plan_production_shot", return_value=plan):
			result = storyboard._plan_project(frappe.get_doc("Media Project", self.project.name), set(), True)

		self.assertTrue(result[0]["held_back"])
		self.assertEqual("Original.", frappe.get_doc("Shot", self.shot.name).generation_prompt)


class TestRealtimeAndBackgroundPlanning(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Realtime",
				"workflow": _create_workflow(),
				"total_duration_seconds": 3,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)

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

	def test_planning_job_id_is_unique_per_requested_scope(self):
		from joymedia.api import storyboard

		all_shots = storyboard._planning_job_id(self.project.name, None)
		first = storyboard._planning_job_id(self.project.name, ["SHOT-1"])
		first_again = storyboard._planning_job_id(self.project.name, '["SHOT-1"]')
		self.assertNotEqual(all_shots, first)
		self.assertEqual(first, first_again)

	def test_the_job_reports_start_progress_and_completion(self):
		from joymedia.api import storyboard

		def fake_plan(project, wanted, apply, progress=None):
			progress(1, 1, {"shot_name": "Hook", "held_back": False, "notes": []})
			return [{"held_back": False}]

		with (
			patch.object(storyboard, "_plan_project", side_effect=fake_plan),
			patch("joymedia.services.project.realtime.frappe.publish_realtime") as publish,
		):
			storyboard.run_planning_job(self.project.name, None, "Administrator")
		states = [c.args[1]["state"] for c in publish.call_args_list]
		self.assertEqual(["started", "running", "done"], states)
		# Progress must not wait for the job's final commit, or it all arrives in one burst at the end.
		self.assertTrue(all(c.kwargs["after_commit"] is False for c in publish.call_args_list))

	def test_a_failed_job_tells_the_studio_why(self):
		from joymedia.api import storyboard

		with (
			patch.object(storyboard, "_plan_project", side_effect=frappe.ValidationError("planner down")),
			patch("joymedia.services.project.realtime.frappe.publish_realtime") as publish,
			self.assertRaises(frappe.ValidationError),
		):
			storyboard.run_planning_job(self.project.name, None, "Administrator")
		last = publish.call_args_list[-1].args[1]
		self.assertEqual("failed", last["state"])
		self.assertIn("planner down", last["error"])


class TestGrounding(FrappeTestCase):
	REFS: ClassVar[list] = [
		{"key": "mascot", "label": "Gau Shera mascot", "role": "Character"},
		{"key": "pack", "label": "Shera pack", "role": "Product"},
	]
	PROJECT = frappe._dict(product_name="Khăn giấy rút cao cấp Shera", project_name="P")

	def test_a_beat_that_names_the_product_gets_its_reference_even_if_the_planner_missed_it(self):
		beat = {
			"raw": "Gấu con rút từng tờ giấy Shera ra khỏi bịch",
			"camera": "",
			"action": "The cub pulls tissue",
		}
		keys, notes = planner.ground_reference_keys(self.PROJECT, beat, ["mascot"], self.REFS)
		self.assertEqual(["mascot", "pack"], keys)
		self.assertTrue(notes)

	def test_a_beat_about_something_else_is_left_alone(self):
		beat = {"raw": "Cảnh toàn thành phố lúc hoàng hôn", "camera": "", "action": "A city at dusk"}
		self.assertEqual(
			(["mascot"], []), planner.ground_reference_keys(self.PROJECT, beat, ["mascot"], self.REFS)
		)

	def test_the_characters_own_name_does_not_count_as_mentioning_the_product(self):
		# 'Shera' is also in the mascot's label, so it must not pull the pack into every scene by itself.
		beat = {"raw": "Gấu mẹ Shera nhảy múa", "camera": "", "action": "Mother Shera bear dances"}
		keys, _ = planner.ground_reference_keys(self.PROJECT, beat, ["mascot"], self.REFS)
		self.assertEqual(["mascot"], keys)

	def test_an_already_chosen_product_is_not_duplicated(self):
		beat = {"raw": "giấy Shera", "camera": "", "action": ""}
		self.assertEqual(
			(["pack"], []), planner.ground_reference_keys(self.PROJECT, beat, ["pack"], self.REFS)
		)

	def test_resolved_pack_prompt_binds_product_even_when_the_beat_omitted_it(self):
		plan = {
			"image_prompt": "A mascot holds the branded tissue pack at a kitchen table.",
			"video_prompt": "The mascot pulls one sheet from the pack.",
			"start_state": "The pack is held in both paws.",
			"end_state": "One tissue sheet is visible.",
		}
		keys, notes = planner.ground_visible_product_keys(self.PROJECT, plan, ["mascot"], self.REFS)
		self.assertEqual(["mascot", "pack"], keys)
		self.assertTrue(notes)

	def test_plain_tissue_sheet_does_not_bind_a_pack_that_is_not_visible(self):
		plan = {
			"image_prompt": "Macro view of one white tissue sheet on a wooden surface.",
			"video_prompt": "Water beads absorb into the tissue sheet.",
			"start_state": "The sheet lies flat.",
			"end_state": "The sheet remains intact.",
		}
		self.assertEqual(
			(["mascot"], []), planner.ground_visible_product_keys(self.PROJECT, plan, ["mascot"], self.REFS)
		)

	def test_product_lock_boilerplate_cannot_add_pack_to_tissue_only_scene(self):
		plan = {
			"image_prompt": "Mascot holds one tissue. Product orientation is locked to the selected source view. "
			"The package must contact its support.",
			"start_state": "The pack remains open outside the close-up.",
		}
		beat = {
			"products": [],
			"camera": "Close-up of a mascot holding one tissue",
			"action": "The tissue touches a wet surface",
			"raw": "",
		}
		self.assertEqual(
			(["mascot"], []),
			planner.ground_visible_product_keys(self.PROJECT, plan, ["mascot"], self.REFS, beat=beat),
		)
		self.assertEqual(
			(["mascot"], []),
			planner.ground_visible_product_keys(self.PROJECT, plan, ["mascot", "pack"], self.REFS, beat=beat),
		)
		beat["camera"] = "Close-up of the mascot holding the branded pack"
		self.assertEqual(
			["mascot", "pack"],
			planner.ground_visible_product_keys(self.PROJECT, plan, ["mascot"], self.REFS, beat=beat)[0],
		)

	def test_a_character_is_added_when_the_beat_uses_a_distinctive_word_of_its_label(self):
		beat = {"raw": "Gấu con hoảng hốt", "camera": "", "action": "The bear cub panics"}
		keys, notes = planner.ground_reference_keys(self.PROJECT, beat, ["pack"], self.REFS)
		self.assertEqual(["pack", "mascot"], keys)
		self.assertTrue(any("mascot" in n.lower() for n in notes))

	def test_identical_planner_requests_are_answered_from_the_cache(self):
		answers = iter([{"n": 1}, {"n": 2}])
		prompt = "same prompt " + frappe.generate_hash(length=12)
		with patch.object(planner, "_request_planner", side_effect=lambda *a, **k: next(answers)) as ask:
			first = planner._ask_planner(prompt, system="s")
			planner._ask_planner(prompt + " different", system="s")
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


class TestFollowTheSheet(FrappeTestCase):
	REFS: ClassVar[list] = [
		{"key": "me", "label": "Gấu mẹ (mother mascot)", "role": "Character"},
		{"key": "con", "label": "Gấu con (kid mascot)", "role": "Character"},
		{"key": "green", "label": "Soft pack green", "role": "Product"},
		{"key": "pink", "label": "Soft pack pink", "role": "Product"},
		{"key": "logo", "label": "Brand logo", "role": "Logo"},
	]

	def _plan(self, raw, summary, number=3, total=6, motion="The mother lifts a tissue."):
		project = frappe._dict(product_name="Soft tissue paper", name="P", planning_mode="Follow the sheet")
		beat = {
			"raw": raw,
			"summary": summary,
			"camera": "",
			"action": "",
			"audio": "SFX: pop",
			"voice_over": "",
			"on_screen_text": "",
		}
		shot = frappe._dict(shot_number=number, duration_seconds=5)
		with (
			patch.object(planner, "motion_only", side_effect=lambda *a, **k: motion),
			patch.object(planner, "_place", return_value="A kitchen."),
			patch.object(frappe.db, "count", return_value=total),
			patch.object(planner, "translate", side_effect=lambda text, project, about="": text),
		):
			return planner.follow_the_sheet(project, shot, beat, self.REFS)

	def test_only_the_characters_the_beat_names_appear_and_one_pack_when_the_beat_names_the_pack(self):
		self.assertEqual(
			["me"], self._plan("Gấu mẹ rút một tờ giấy", "The mother pulls a tissue sheet.")["reference_keys"]
		)
		self.assertEqual(
			["me", "green"],
			self._plan("Gấu mẹ rút giấy từ bịch", "The mother pulls tissue from the pack.")["reference_keys"],
		)

	def test_a_name_inside_another_phrase_is_not_a_character_in_the_scene(self):
		# "sợ mẹ mắng" (afraid mother will scold) mentions mother, who is not in the scene.
		# The ordinary paper the kid grabs is not the advertised pack either.
		plan = self._plan(
			"Gấu con sợ mẹ mắng, lấy giấy lau", "The kid, afraid of the scolding, grabs paper.", number=2
		)
		self.assertEqual(["con"], plan["reference_keys"])

	def test_the_word_family_brings_in_every_family_member(self):
		for raw in ("Cả gia đình quây quần bên bàn", "The whole family laughs together"):
			self.assertEqual(
				["me", "con"], self._plan(raw, "The family sits together.")["reference_keys"], raw
			)

	def test_all_products_when_the_beat_says_products_and_the_logo_bookends_the_film(self):
		plan = self._plan(
			"Gấu mẹ ... các sản phẩm giấy", "The mother stands with all the products.", number=6, total=6
		)
		self.assertEqual(["me", "green", "pink", "logo"], plan["reference_keys"])
		first = self._plan("Gấu con", "The kid sits.", number=1, total=6)
		self.assertIn("logo", first["reference_keys"])

	def test_the_movement_is_english_and_the_sheets_own_sound_is_kept(self):
		plan = self._plan("Gấu mẹ", "The mother waves.", motion="Gấu mẹ vẫy tay.")
		self.assertEqual(
			"The mother waves.", plan["video_prompt"]
		)  # the beat's own English, not the failed rewrite
		self.assertTrue(plan["audio"].startswith("Audio:"))
		self.assertFalse(plan["held_back"])

	def test_english_is_judged_by_letters_not_punctuation(self):
		self.assertTrue(planner.looks_english("Top-down → macro close-up — “fast” motion…"))
		self.assertFalse(planner.looks_english("Gấu mẹ cầm tờ giấy"))
		self.assertFalse(planner.looks_english("đổ"))

	def test_a_beat_with_no_place_keeps_the_previous_scenes_place(self):
		project = frappe._dict(product_name="Soft tissue", name="P", planning_mode="Follow the sheet")
		beat = {
			"raw": "x",
			"summary": "The mother waves.",
			"camera": "",
			"action": "",
			"audio": "",
			"voice_over": "",
			"on_screen_text": "",
		}
		with (
			patch.object(planner, "motion_only", return_value="The mother waves."),
			patch.object(planner, "_place", return_value=""),
			patch.object(frappe.db, "count", return_value=6),
			patch.object(planner, "translate", side_effect=lambda t, p: t),
		):
			plan = planner.follow_the_sheet(
				project,
				frappe._dict(shot_number=2, duration_seconds=5),
				beat,
				TestFollowTheSheet.REFS,
				"A sunny kitchen.",
			)
		self.assertEqual("A sunny kitchen.", plan["setting_prompt"])

	def test_an_action_sentence_is_not_accepted_as_a_place(self):
		with patch.object(
			planner,
			"_ask_planner",
			return_value={"place": "Water stain on table is immediately absorbed clean."},
		):
			self.assertEqual(
				"", planner._place(frappe._dict(), {"summary": "Water on the table is absorbed."})
			)
		with patch.object(
			planner, "_ask_planner", return_value={"place": "A warm family kitchen with sunlight."}
		):
			self.assertEqual(
				"A warm family kitchen with sunlight.",
				planner._place(frappe._dict(), {"summary": "In the kitchen she waves."}),
			)

	def test_a_rewrite_that_invents_is_rejected_for_the_sheets_own_words(self):
		project = frappe._dict(product_name="Tissue", name="P", planning_mode="Follow the sheet")
		beat = {
			"raw": "Gấu mẹ",
			"summary": "x",
			"action": "The mother presses a tissue to the kid's cheek.",
			"camera": "",
			"audio": "",
			"voice_over": "",
			"on_screen_text": "",
		}
		with (
			patch.object(planner, "motion_only", return_value="A dress absorbs red wine at a party."),
			patch.object(planner, "_place", return_value=""),
			patch.object(frappe.db, "count", return_value=6),
			patch.object(planner, "translate", side_effect=lambda t, p: t),
		):
			plan = planner.follow_the_sheet(
				project, frappe._dict(shot_number=4, duration_seconds=8), beat, TestFollowTheSheet.REFS
			)
		self.assertEqual("The mother presses a tissue to the kid's cheek.", plan["video_prompt"])

	def test_a_failed_rewrite_falls_back_to_the_beats_english_translation_not_a_placeholder(self):
		project = frappe._dict(product_name="Tissue", name="P", planning_mode="Follow the sheet")
		beat = {
			"raw": "Gấu mẹ",
			"summary": "The mother lifts the wet sheet.",
			"camera": "",
			"action": "",
			"audio": "",
			"voice_over": "",
			"on_screen_text": "",
		}
		with (
			patch.object(planner, "motion_only", return_value="Gấu mẹ nhấc tờ giấy"),
			patch.object(planner, "_place", return_value=""),
			patch.object(frappe.db, "count", return_value=6),
			patch.object(planner, "translate", side_effect=lambda t, p: t),
		):
			plan = planner.follow_the_sheet(
				project, frappe._dict(shot_number=3, duration_seconds=8), beat, TestFollowTheSheet.REFS
			)
		self.assertEqual("The mother lifts the wet sheet.", plan["video_prompt"])

	def _split(self, action):
		project = frappe._dict(product_name="Tissue", name="P", planning_mode="Follow the sheet")
		beat = {
			"raw": "Split-screen",
			"summary": "Tissues in three places.",
			"camera": "Split-screen (chia 3 màn hình)",
			"action": action,
			"audio": "",
			"voice_over": "",
			"on_screen_text": "",
		}
		english = {
			"Bàn ăn gia đình": "Family dining table",
			"Trên thảm picnic ngoài trời": "On a picnic mat outdoors",
			"Trong túi xách/ balo": "Inside a handbag/backpack",
		}
		with (
			patch.object(planner, "motion_only", return_value="Tissues in three places.") as motion,
			patch.object(planner, "_place", return_value="Dining table, picnic, handbag."),
			patch.object(frappe.db, "count", return_value=6),
			patch.object(
				planner,
				"translate",
				side_effect=lambda t, p, about="": english.get(
					t,
					"Tissues placed in settings across 3 angles: 1. Family dining table 2. On a picnic mat outdoors 3. Inside a handbag/backpack",
				),
			),
		):
			plan = planner.follow_the_sheet(
				project,
				frappe._dict(shot_number=5, duration_seconds=4),
				beat,
				TestFollowTheSheet.REFS,
				"A kitchen.",
			)
		return plan, motion

	def test_a_split_screen_keeps_every_view_of_the_sheet_and_the_films_place(self):
		plan, motion = self._split(
			"Giấy ăn đặt trong các bối cảnh qua 3 góc:\n1. Bàn ăn gia đình\n2. Trên thảm picnic ngoài trời\n3. Trong túi xách/ balo"
		)
		self.assertEqual(
			["Family dining table", "On a picnic mat outdoors", "Inside a handbag/backpack"],
			[v["text"] for v in plan["views"]],
		)
		self.assertEqual("Trong túi xách/ balo", plan["views"][2]["source"])
		self.assertTrue(
			plan["video_prompt"].startswith(
				"Split screen of 3 stacked panels, top to bottom: 1. Family dining table; 2. On a picnic mat outdoors; 3. Inside a "
				"handbag/backpack. Tissues in three places."
			),
			plan["video_prompt"],
		)
		self.assertEqual(1, plan["video_prompt"].count("Family dining table"))  # the list is not repeated
		motion.assert_not_called()  # no rewrite that could drop a view
		self.assertEqual("A kitchen.", plan["setting_prompt"])
		self.assertFalse(any("Needs editing" in n for n in plan["notes"]))

	def test_a_split_screen_without_numbered_views_is_flagged(self):
		plan, _motion = self._split("Ba khung hình khác nhau")
		self.assertEqual([], plan["views"])
		self.assertTrue(any("Needs editing" in n for n in plan["notes"]))

	def test_a_text_the_model_will_not_translate_whole_is_translated_by_sentence(self):
		project = frappe._dict(product_name="Tissue", project_name="P", selected_media=[])
		answers = {
			"Gấu con làm đổ cốc nước. Gấu con hoảng hốt.": {
				"english": "Gấu con làm đổ cốc nước. Gấu con hoảng hốt."
			},
			"Gấu con làm đổ cốc nước.": {"english": "The kid knocks over the glass."},
			"Gấu con hoảng hốt.": {"english": "The kid panics."},
		}
		with patch.object(
			planner,
			"_ask_planner",
			side_effect=lambda prompt, **k: next(
				(v for key, v in answers.items() if f"TEXT: {key}" in prompt), {"english": ""}
			),
		):
			self.assertEqual(
				"The kid knocks over the glass. The kid panics.",
				planner.translate("Gấu con làm đổ cốc nước. Gấu con hoảng hốt.", project),
			)


class TestFaithfulTranslation(FrappeTestCase):
	def test_the_echoed_source_is_removed_from_an_answer(self):
		from joymedia.services.planning.production import english_part

		self.assertEqual(
			"Baby bear knocks over a glass of juice. The baby bear panics.",
			english_part(
				"Gấu con làm đổ cả cốc nước ép.: Baby bear knocks over a glass of juice. Gấu con hoảng hốt: The baby bear panics."
			),
		)
		self.assertEqual(
			"The paper shreds.", english_part("Giấy bị mủn rách translates to: The paper shreds.")
		)
		self.assertEqual(
			"Kid knocks the glass over.", english_part("Gấu con làm đổ cốc. (Kid knocks the glass over.)")
		)
		# English that names a character in the source language is kept whole.
		self.assertEqual(
			"Gấu con knocks over a glass of juice.", english_part("Gấu con knocks over a glass of juice.")
		)

	def test_a_translation_that_adds_names_or_brands_is_caught(self):
		from joymedia.services.planning.production import invented_names

		source = "Góc quay: Toàn cảnh -> Cận cảnh. Hiệu ứng ánh sáng quanh hộp giấy"
		self.assertEqual(
			set(), invented_names("Wide to close shot: Light glows around the paper box.", source)
		)
		self.assertTrue(invented_names("Wide shot. Gấu mẹ floats in a studio. Shera logo glows.", source))

	def test_a_sound_cue_is_translated_with_its_scene_as_context(self):
		from joymedia.services.planning import production

		project = frappe._dict(product_name="Tissue", project_name="P", selected_media=[])
		with patch.object(
			production, "_ask_planner", return_value={"english": "Sound of a glass falling over"}
		) as ask:
			production.translate("Tiếng cốc đổ", project, about="The kid spills juice.")
		self.assertIn("The text belongs to this scene: The kid spills juice.", ask.call_args.args[0])


class TestSceneFidelity(FrappeTestCase):
	def test_the_product_is_in_a_scene_only_when_its_brand_or_pack_is_named(self):
		from joymedia.services.planning.production import brand_words, shows_product

		project = frappe._dict(product_name="Khăn giấy rút cao cấp Shera (300 tờ - 4 lớp)")
		self.assertEqual({"shera"}, brand_words(project.product_name))
		self.assertFalse(shows_product(project, "Gấu con lấy giấy ăn thường lau nhưng giấy bị mủn rách"))
		self.assertTrue(shows_product(project, "Gấu mẹ ôm bịch giấy Shera siêu to"))
		self.assertTrue(shows_product(project, "Các sản phẩm ở giữa khung hình"))
		self.assertTrue(shows_product(project, "The mother holds the pack"))

	def test_the_sheets_camera_direction_is_kept_without_its_labels(self):
		from joymedia.services.planning.production import camera_direction

		self.assertEqual(
			"Close-up of family dining table. Slow-motion.",
			camera_direction("Camera angle: Close-up of family dining table.\nCamera movement. Slow-motion."),
		)
		self.assertEqual(
			"", camera_direction("Góc quay: Cận cảnh")
		)  # an untranslated line is left out, never sent as is

	def test_character_names_become_english_roles(self):
		from joymedia.services.planning.production import english_roles

		references = [
			{"role": "Character", "label": "Gấu con (kid mascot)"},
			{"role": "Product", "label": "Pack"},
		]
		self.assertEqual(
			"The kid character spills juice.", english_roles("Gấu con spills juice.", references)
		)

	def test_the_sheets_music_is_left_out_when_the_film_has_sound_effects_only(self):
		from joymedia.services.planning import production

		beat = {"audio": "SFX: Tiếng cốc đổ\nBGM: Dồn dập", "action": "The kid spills juice."}
		with patch.object(production, "translate", side_effect=lambda text, project, about="": f"<{text}>"):
			effects = production.audio_direction(frappe._dict(soundtrack_mode="Sound effects only"), beat)
			full = production.audio_direction(frappe._dict(soundtrack_mode="Full soundtrack"), beat)
		self.assertNotIn("music", effects)
		self.assertIn("music", full)


class TestCameraAndRewrites(FrappeTestCase):
	def test_vietnamese_camera_terms_are_read_without_the_language_model(self):
		from joymedia.services.planning.production import camera_glossary

		self.assertEqual(
			"wide shot to close-up", camera_glossary("Góc quay: Toàn cảnh -> Cận cảnh (Wide to Medium Shot)")
		)
		self.assertEqual(
			"top-down to extreme close-up", camera_glossary("Top-down (từ trên xuống) -> Macro siêu cận cảnh")
		)
		self.assertEqual(
			"close-up, side angle, soft light",
			camera_glossary("Cận cảnh góc nghiêng (Close-up, ánh sáng dịu nhẹ)"),
		)
		self.assertEqual("", camera_glossary("Ánh sáng ấm"))

	def test_a_rewrite_that_adds_content_is_measured(self):
		from joymedia.services.planning.production import added_share

		source = "Shera napkins on the family dining table."
		self.assertLess(added_share(source, "Shera napkins rest on the family dining table."), 0.35)
		self.assertGreater(
			added_share(
				source, "Family members pour refreshing drinks while the camera zooms on smiling faces."
			),
			0.35,
		)


class TestFaithfulRewrite(FrappeTestCase):
	def test_an_inventing_rewrite_is_replaced_by_the_beats_own_english(self):
		project = frappe._dict(product_name="P", project_name="P", selected_media=[])
		source = "Shera napkins on the family dining table."
		with patch.object(
			planner,
			"motion_only",
			return_value="Family members pour drinks and parents exchange loving glances.",
		):
			self.assertEqual(source, planner.faithful_rewrite(project, source, []))
		with patch.object(
			planner, "motion_only", return_value="Shera napkins rest on the family dining table."
		):
			self.assertEqual(
				"Shera napkins rest on the family dining table.",
				planner.faithful_rewrite(project, source, []),
			)


class TestRewriteKeepsEverySentence(FrappeTestCase):
	def test_a_rewrite_that_drops_a_sentence_is_refused_even_when_most_words_are_kept(self):
		source = (
			"Mother mascot pulls out 1 sheet of paper and places it gently on the water puddle. Water stain on table is "
			"immediately absorbed clean. Mother mascot lifts up the soaked wet sheet and shakes it taut. Paper remains intact "
			"and unbroken, not torn."
		)
		dropped = source.rsplit(" Paper remains", 1)[0]
		self.assertGreaterEqual(planner.beat_coverage(source, dropped)[0], planner.MIN_REWRITE_COVERAGE)
		self.assertFalse(planner.keeps_every_sentence(source, dropped))
		self.assertTrue(
			planner.keeps_every_sentence(source, source.replace("Mother mascot", "The mother mascot"))
		)
		project = frappe._dict(product_name="Tissue")
		with patch.object(planner, "motion_only", return_value=dropped):
			self.assertEqual(source, planner.faithful_rewrite(project, source, [], "the mother mascot"))


class TestCameraGlossaryKeepsDetails(FrappeTestCase):
	def test_the_glossary_fixes_the_framing_and_keeps_the_columns_other_details(self):
		self.assertEqual(
			"Wide shot to close-up. Sparkling light radiates around the tissue pack.",
			planner.with_glossary(
				"Panorama to near view (Wide to Medium Shot). Sparkling light radiates around the tissue pack.",
				"wide shot to close-up",
			),
		)
		# Where things stand in the frame is a detail, not framing.
		self.assertEqual(
			"Medium shot, front view. Eye-level. Mother bear (right corner of the frame) + all products (centre).",
			planner.with_glossary(
				"Medium shot, eye-level. Mother bear (right corner of the frame) + all products (centre).",
				"medium shot, front view",
			),
		)
		# A camera move the glossary does not cover is kept; the same framing in other words is not repeated.
		self.assertEqual(
			"Front view. Hero packshot. Very slight push-in.",
			planner.with_glossary("Hero packshot, front angle, very slight push-in.", "front view"),
		)


class TestNamedSceneContents(FrappeTestCase):
	REFS: ClassVar[list] = [
		{"key": "me", "label": "Gấu mẹ (mother mascot)", "role": "Character"},
		{"key": "con", "label": "Gấu con (kid mascot)", "role": "Character"},
		{"key": "green", "label": "Shera 400 tờ", "role": "Product"},
		{"key": "pink", "label": "Shera cuộn", "role": "Product"},
	]

	def _plan(self, **named):
		project = frappe._dict(product_name="Khăn giấy Shera", name="P", planning_mode="Follow the sheet")
		beat = {
			"raw": "Gấu mẹ và gấu con lau bàn bằng giấy Shera",
			"summary": "The mother and the kid wipe the table.",
			"camera": "",
			"action": "",
			"audio": "",
			"voice_over": "",
			"on_screen_text": "",
			"cast": [],
			"products": [],
			"place": "",
			"rules": "",
			**named,
		}
		with (
			patch.object(planner, "motion_only", return_value="The mother and the kid wipe the table."),
			patch.object(planner, "_place", return_value="A kitchen."),
			patch.object(frappe.db, "count", return_value=6),
			patch.object(
				planner,
				"translate",
				side_effect=lambda text, project, about="": {"Phòng nhỏ ấm áp": "A small warm room"}.get(
					text, text
				),
			),
			patch(
				"joymedia.services.intake.references.place_row",
				return_value={"description": "Phòng nhỏ ấm áp"},
			),
		):
			return planner.follow_the_sheet(
				project, frappe._dict(shot_number=3, duration_seconds=5), beat, self.REFS
			)

	def test_the_named_cast_and_products_are_exactly_the_scenes_references(self):
		plan = self._plan(cast=["Gấu con"], products=["Shera 400 tờ"])
		self.assertEqual(["con", "green"], plan["reference_keys"])  # not the mother the action also names

	def test_explicit_empty_entity_columns_do_not_infer_cast_or_products(self):
		self.assertEqual([], self._plan(cast_declared=True, products_declared=True)["reference_keys"])

	def test_a_name_without_a_picture_is_reported_not_guessed(self):
		plan = self._plan(cast=["Gấu bố"], products=["Shera 400 tờ"])
		self.assertEqual(["green"], plan["reference_keys"])
		self.assertTrue(any("Gấu bố" in note for note in plan["notes"]))

	def test_a_named_place_gives_every_scene_set_there_the_same_setting_and_the_rules_follow_the_action(self):
		plan = self._plan(place="Phòng khách", rules="The cup does not break.")
		self.assertEqual("A small warm room", plan["setting_prompt"])
		self.assertTrue(plan["video_prompt"].endswith("\n\nRules: The cup does not break."))

	def test_without_names_the_scene_is_read_from_the_action_as_before(self):
		self.assertEqual(["me", "con", "green"], self._plan()["reference_keys"])


class TestSheetRulesReachThePrompts(FrappeTestCase):
	def test_the_places_rule_and_the_props_the_scene_names_join_its_rules(self):
		refs = [{"key": "con", "label": "Gấu con", "role": "Character"}]
		project = frappe._dict(product_name="Khăn giấy Shera", name="P", planning_mode="Follow the sheet")
		beat = {
			"raw": "Gấu con làm đổ cốc nước ép",
			"summary": "The kid spills the cup of juice.",
			"camera": "",
			"action": "",
			"audio": "",
			"voice_over": "",
			"on_screen_text": "",
			"cast": ["Gấu con"],
			"products": [],
			"place": "Phòng khách",
			"rules": "The cup does not break",
		}
		english = {
			"Phòng nhỏ": "A small room",
			"Một bàn, một cốc cho mọi cảnh": "One table and one cup in every scene",
			"Cốc nước: cốc thuỷ tinh trong": "Cup of water: a clear glass",
		}
		with (
			patch.object(planner, "motion_only", return_value="The kid spills the cup of juice."),
			patch.object(planner, "_place", return_value=""),
			patch.object(frappe.db, "count", return_value=6),
			patch.object(
				planner, "translate", side_effect=lambda text, project, about="": english.get(text, text)
			),
			patch(
				"joymedia.services.intake.references.place_row",
				return_value={"description": "Phòng nhỏ", "keep_rule": "Một bàn, một cốc cho mọi cảnh"},
			),
			patch(
				"joymedia.services.intake.references.sheet_references",
				return_value=[
					{"name": "Cốc nước", "role": "Prop", "description": "cốc thuỷ tinh trong"},
					{"name": "Đĩa bánh", "role": "Prop", "description": "đĩa sứ"},
				],
			),
		):
			plan = planner.follow_the_sheet(
				project, frappe._dict(shot_number=2, duration_seconds=4), beat, refs
			)
		self.assertTrue(
			plan["video_prompt"].endswith(
				"\n\nRules: The cup does not break; One table and one cup in every scene; Cup of water: a clear glass."
			),
			plan["video_prompt"],
		)
		self.assertNotIn("đĩa", plan["video_prompt"].casefold())  # a prop the scene does not name stays out

	def test_the_brand_sheet_reaches_the_planner(self):
		project = frappe._dict(
			storyboard_source_json=frappe.as_json(
				{
					"brand": {
						"key_message": "Mềm và dai",
						"claims": "4 lớp\nThấm hút tốt",
						"avoid": "Không nói 'siêu'",
					}
				}
			)
		)
		self.assertEqual(
			[
				"KEY MESSAGE: Mềm và dai",
				"APPROVED CLAIMS (the only product benefits that may be shown or said): 4 lớp | Thấm hút tốt",
				"MUST NOT SAY OR SHOW: Không nói 'siêu'",
			],
			planner.brand_lines(project),
		)


class TestNoPrintableNamesInPrompts(FrappeTestCase):
	def test_the_products_own_name_becomes_the_product_pack(self):
		refs = [
			{"role": "Product", "label": "Giấy lụa rút Shera 400 tờ (Giấy lụa rút Shera 400 tờ / 4 lớp.)"}
		]
		text = "On the table: the GIẤY LỤA RÚT SHERA 400 TỜ / 4 LỚP package and a Giấy lụa rút Shera 400 tờ."
		self.assertEqual(
			"On the table: the advertised product and the advertised product.",
			planner.english_roles(text, refs, "GIẤY LỤA RÚT SHERA 400 TỜ / 4 LỚP"),
		)

	def test_colour_words_are_given_to_the_translator(self):
		self.assertEqual(
			["hồng = pink", "trắng = white"], planner.colour_terms("Ôm trái tim hồng trên nền trắng")
		)
		self.assertEqual([], planner.colour_terms("Cảm giác êm ái"))
		self.assertEqual(["xanh lá = green"], planner.colour_terms("lá cây xanh lá"))


class TestReferenceOptions(FrappeTestCase):
	def test_a_multi_view_character_is_not_described_by_its_canonical_photos_pose_and_props(self):
		from joymedia.services.planning.production import project_reference_options

		rows = [
			frappe._dict(
				reference_key="mascot_front",
				identity_key="mascot",
				reference_role="Character",
				asset_version="A",
				label="mascot_front",
			),
			frappe._dict(
				reference_key="pose_seated",
				identity_key="mascot",
				reference_role="Character",
				asset_version="B",
				label="seated view",
			),
			frappe._dict(
				reference_key="pack",
				identity_key="pack",
				reference_role="Product",
				asset_version="C",
				label="pack",
			),
		]
		analyses = {
			"A": {"description": "A seated bear hugging a pink heart."},
			"C": {"description": "A blue tissue pack, front view."},
		}

		def value(doctype, name, field):
			if field == "media_asset":
				return "MA-" + name
			if field == "media_type":
				return "Image"
			return frappe.as_json(analyses.get(name, {}))

		with patch("frappe.db.get_value", side_effect=value):
			options = {
				row["key"]: row for row in project_reference_options(frappe._dict(selected_media=rows))
			}
		self.assertNotIn("heart", options["mascot_front"]["description"])
		self.assertIn("2 approved views", options["mascot_front"]["description"])
		# A single photograph still tells the planner what it shows.
		self.assertIn("tissue pack", options["pack"]["description"])


class TestUnauthoredPackage(FrappeTestCase):
	def test_offscreen_and_excluded_packages_do_not_expand_visible_inventory(self):
		from joymedia.services.planning.production import _visible_package_words

		for text in (
			"The pack stays outside the close-up.",
			"Mascot holds one loose tissue, without any box.",
			"No packages. Show the folded paper.",
		):
			with self.subTest(text=text):
				self.assertFalse(_visible_package_words(text))
		self.assertTrue(_visible_package_words("Two boxes stand beside the mascot."))
		self.assertTrue(_visible_package_words("No fur on the mascot, which holds a box."))

	def test_empty_product_roster_constrains_both_boundaries_and_motion(self):
		from joymedia.services.planning.production import ground_visible_product_keys

		plan = {
			"image_prompt": "Seated mascot holding a tissue on the rug.",
			"start_state": "Seated mascot beside an open pack, holding a tissue on the rug.",
			"end_state": "Seated mascot holding a folded tissue beside the box on the rug.",
			"video_prompt": "The seated mascot folds the tissue beside the pack.",
		}
		with patch(
			"joymedia.services.planning.production._ask_planner",
			side_effect=[
				{"image_prompt": "Seated mascot holding a tissue on the rug."},
				{"image_prompt": "Seated mascot holding a folded tissue on the rug."},
				{"image_prompt": "The seated mascot folds the tissue."},
			],
		) as rewrite:
			keys, notes = ground_visible_product_keys(
				frappe._dict(),
				plan,
				["mascot", "pack"],
				[{"key": "pack", "role": "Product"}],
				beat={"products": [], "camera": "Seated mascot holds a loose tissue on the rug."},
			)
		self.assertEqual(["mascot"], keys)
		self.assertEqual(3, rewrite.call_count)
		self.assertEqual(3, len(notes))
		self.assertIn("folded tissue", plan["end_state"])
		self.assertIn("rug", plan["start_state"])
		self.assertEqual("The seated mascot folds the tissue.", plan["video_prompt"])

	def test_pack_continuity_does_not_override_a_declared_empty_closeup_roster(self):
		plan = {
			"image_prompt": "Mascot holds a tissue beside the pack.",
			"video_prompt": "Fold the tissue. Rules: the pack remains stationary on the rug.",
		}
		with patch.object(
			planner,
			"_without_unauthored_package",
			side_effect=lambda text, *a, **kw: "Mascot holds and folds one loose tissue.",
		):
			keys, _ = planner.ground_visible_product_keys(
				frappe._dict(),
				plan,
				["mascot", "pack"],
				[{"key": "pack", "role": "Product"}],
				beat={
					"products": [],
					"products_declared": True,
					"camera": "Close-up of the mascot holding one tissue.",
					"action": "Fold the tissue.",
					"rules": "The pack remains stationary on the rug.",
				},
			)
		self.assertEqual(["mascot"], keys)
		self.assertNotIn("pack", plan["image_prompt"])
		self.assertNotIn("pack", plan["video_prompt"])

	def test_standalone_package_world_state_is_omitted_without_rewriting_held_material(self):
		text = "The mascot is seated on the rug, holding a tissue in one paw, the other arm remains relaxed. The Shera Facial pack is stationary on the rug."
		with patch.object(planner, "_ask_planner", side_effect=AssertionError("No model rewrite needed")):
			result = planner._without_unauthored_package(text, [], description="starting state")
		self.assertEqual(text.split(" The Shera")[0], result)
		self.assertFalse(
			planner._visible_package_words("No facial pack or any other package is present on the rug.")
		)
		self.assertTrue(planner._visible_package_words("No fur on the mascot, which holds a box."))

	def test_explicit_empty_product_roster_cannot_silently_add_a_handled_pack(self):
		with self.assertRaisesRegex(ValueError, "declares no visible product"):
			planner.ground_visible_product_keys(
				frappe._dict(),
				{},
				["mascot"],
				[{"key": "pack", "role": "Product"}],
				beat={
					"products": [],
					"products_declared": True,
					"camera": "Mascot holds the pack.",
				},
			)

	def test_failed_package_removal_cannot_leave_unbound_boundary_objects(self):
		from joymedia.services.planning.production import ground_visible_product_keys

		with (
			patch("joymedia.services.planning.production._ask_planner", side_effect=RuntimeError("offline")),
			self.assertRaisesRegex(ValueError, "starting state.*absent"),
		):
			ground_visible_product_keys(
				frappe._dict(),
				{"image_prompt": "Mascot holding a tissue.", "start_state": "Mascot beside a pack."},
				["mascot"],
				[],
				beat={"products": [], "camera": "Mascot holding a loose tissue."},
			)

	def test_a_package_the_script_does_not_show_is_removed_from_the_opening_still(self):
		from joymedia.services.planning.production import _without_unauthored_package

		carried = "A bear seated on the ground, holding a tissue pack with one paw, a puddle nearby."
		for answer, expected, note in (
			(
				{"image_prompt": "A bear seated on the ground holding one tissue, a puddle nearby."},
				"holding one tissue",
				"Removed",
			),
			({"image_prompt": "A bear holding the pack."}, carried, "names a package"),
			(RuntimeError("offline"), carried, "names a package"),
		):
			notes = []
			with (
				self.subTest(answer=answer),
				patch(
					"joymedia.services.planning.production._ask_planner",
					**(
						{"side_effect": answer} if isinstance(answer, Exception) else {"return_value": answer}
					),
				),
			):
				self.assertIn(expected, _without_unauthored_package(carried, notes))
			self.assertIn(note, notes[0])
