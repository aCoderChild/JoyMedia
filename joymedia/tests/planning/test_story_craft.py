from unittest import TestCase

from joymedia.services.planning.creative import (
	_validate_character_support_continuity,
	direct_camera,
	story_logic_errors,
)


def scene(action, *, cast=("bear",), framing="medium", stage="present", move="static"):
	return {
		"action": action,
		"cast": list(cast),
		"products": ["pack"],
		"shot_framing": framing,
		"shot_angle": "eye_level",
		"narrative_stage": stage,
		"camera_move": move,
	}


class TestStoryLogic(TestCase):
	def test_character_support_change_requires_visible_transition(self):
		roles = {"bear": {"identity": "mascot"}, "bear_alt": {"identity": "mascot"}}
		scenes = [
			{
				"cast": ["bear"],
				"visual_camera": "The mascot is seated on the floor",
				"action": "It opens the pack.",
			},
			{
				"cast": ["bear_alt"],
				"visual_camera": "The mascot is standing by the table",
				"action": "It wipes water.",
			},
		]
		with self.assertRaisesRegex(ValueError, "without a visible stand-up"):
			_validate_character_support_continuity(scenes, roles)
		scenes[0]["action"] = "The mascot stands up after opening the pack."
		_validate_character_support_continuity(scenes, roles)

	def test_the_same_demonstration_twice_is_rejected(self):
		scenes = [
			scene("[0-3s] The bear holds the tissue up to examine it."),
			scene("[0-3s] The bear wipes crumbs from the table."),
			scene("[0-5s] The bear examines the tissue closely."),
			scene("[0-3s] The bear presents the pack.", stage="hero"),
		]
		self.assertIn(
			"Scenes 1 and 3 repeat the same demonstration (examin the tissue)", story_logic_errors(scenes)
		)

	def test_a_tissue_absorbs_only_liquid_that_exists_on_camera(self):
		crumbs = [scene("[0-5s] The bear wipes the crumbs; the tissue gradually absorbs the crumbs.")]
		self.assertIn(
			"no liquid exists on camera", story_logic_errors([*crumbs, scene("Pack.", stage="hero")])
		)
		spill = [
			scene("[0-3s] The bear knocks the glass and water spills on the table."),
			scene("[0-5s] The bear presses a tissue on the spill and it absorbs the water."),
			scene("[0-3s] The bear presents the pack.", stage="hero"),
		]
		self.assertIsNone(story_logic_errors(spill))


class TestCameraCraft(TestCase):
	def test_a_six_scene_film_opens_moving_never_stalls_and_leaves_eye_level(self):
		scenes = [
			scene("[0-3s] The bear reaches for a cookie.", framing="wide", stage="establish"),
			scene("[0-4s] The bear picks up the pack.", stage="approach"),
			scene("[0-4s] The bear pulls one tissue from the pack.", framing="close_up", stage="extract"),
			scene("[0-4s] The bear holds the tissue to its cheek and smiles.", stage="feel"),
			scene("[0-4s] The bear presents the pack proudly.", stage="present"),
			scene("[0-3s] The pack rests on the table.", cast=(), framing="close_up", stage="hero"),
		]
		direct_camera(scenes)
		moves = [item["camera_move"] for item in scenes]
		self.assertEqual("arc", moves[0])
		self.assertEqual("static", moves[2])  # the precise extraction stays readable
		self.assertEqual("dolly_out", moves[-1])
		self.assertGreaterEqual(sum(move != "static" for move in moves), 3)
		self.assertFalse(
			any(moves[i] == moves[i + 1] == moves[i + 2] == "static" for i in range(len(moves) - 2))
		)
		self.assertLessEqual(sum(item["shot_angle"] == "eye_level" for item in scenes), 3)


class TestRhythm(TestCase):
	def test_equal_weights_become_a_rhythm_with_the_proof_longest(self):
		from joymedia.services.planning.creative import fit_generated_timing

		jobs = ["establish", "detail", "detail", "detail", "feel", "inspect", "hero"]
		actions = ["[0-2s] a, [2-4s] b", "[0-2s] a, [2-4s] b", "[0-1s] a, [1-2s] b, [2-4s] c", "[0-4s] a"]
		script = {
			"scenes": [
				{"duration_seconds": 4, "narrative_stage": job, "action": actions[min(index, 3)]}
				for index, job in enumerate(jobs)
			]
		}
		fit_generated_timing(script, 30, 24, max_scene_frames=124)
		lengths = [scene["duration_seconds"] for scene in script["scenes"]]
		self.assertAlmostEqual(30, sum(lengths), places=3)
		self.assertGreater(len({round(length, 2) for length in lengths}), 2)
		self.assertEqual(max(lengths), lengths[2])  # the multi-step proof beat (ties at shot capacity)
		self.assertLess(lengths[4], lengths[2])  # a reaction is quicker than the proof
		self.assertTrue(all(length <= 124 / 24 for length in lengths))


class TestClosingBeat(TestCase):
	def test_an_early_cta_moves_to_the_final_product_scene(self):
		from joymedia.services.planning.creative import CLOSING_BEAT, normalize_early_closing_beat

		scenes = [
			{"beat_name": "Hook", "products": [], "on_screen_text": ""},
			{"beat_name": "Proof", "products": ["pack"], "on_screen_text": ""},
			{"beat_name": "Packshot CTA", "products": ["pack"], "on_screen_text": "MUA NGAY"},
			{"beat_name": "Smile with the pack", "products": ["pack"], "on_screen_text": ""},
		]
		self.assertTrue(normalize_early_closing_beat({"scenes": scenes}))
		self.assertFalse(any(CLOSING_BEAT.search(scene["beat_name"]) for scene in scenes[:-1]))
		self.assertTrue(CLOSING_BEAT.search(scenes[-1]["beat_name"]))
		self.assertEqual(("", "MUA NGAY"), (scenes[2]["on_screen_text"], scenes[-1]["on_screen_text"]))
