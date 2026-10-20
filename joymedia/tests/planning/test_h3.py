"""Regressions for conflicting cameras, missing media, sound separation and continuations."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning.camera import camera_plan
from joymedia.services.planning.h3 import _without_camera, compile_h3, h3_kind
from joymedia.services.planning.prompts import compile_segment_prompt_from_snapshot


class TestH3(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.framing = patch(
			"joymedia.services.planning.framing.inspect_framing",
			return_value={"status": "assessed", "complete": True, "bounds": [0.15, 0.15, 0.85, 0.85]},
		)
		self.framing.start()
		self.addCleanup(self.framing.stop)

	def shot(self, **values):
		return frappe._dict(
			dict(
				name="S",
				shot_number=1,
				duration_seconds=5,
				generation_prompt="The woman lifts the cup.",
				references=[],
			)
			| values
		)

	def project(self, **values):
		return frappe._dict(dict(generation_mode="Multi-shot", soundtrack_mode="Full soundtrack") | values)

	@patch(
		"joymedia.services.planning.prompts._mood",
		return_value="Warm cinematic live action with soft side light.",
	)
	def test_h3_order_and_exact_speech_are_preserved(self, mood):
		s = self.shot()
		s.generation_prompt = 'The woman lifts the cup and says, "Take the morning with you."\n\nAudio: soft footsteps; music: sparse piano, slow tempo.'
		p = compile_h3(s, self.project())
		self.assertLess(p.index("Warm cinematic"), p.index("first frame controls"))
		self.assertLess(p.index("Begin with"), p.index("The woman lifts"))
		self.assertLess(p.index("The woman lifts"), p.index("The camera makes"))
		self.assertLess(p.index("The camera makes"), p.index("End with"))
		self.assertIn('"Take the morning with you."', p)
		self.assertTrue(p.endswith("non_diegetic_music: sparse piano, slow tempo."))
		self.assertNotIn("piano", p.split("non_diegetic_music:")[0])
		self.assertNotIn("<Picture 2>", p)
		self.assertNotIn("Video 1", p)

	@patch("joymedia.services.planning.prompts._mood", return_value="Warm side light.")
	def test_timed_action_is_not_duplicated_but_event_constraints_are_preserved(self, mood):
		shot = self.shot(
			motion_plan_json={
				"actions": [{"start": 0, "end": 2, "action": "The subject lifts the cup."}],
				"scene_contract": {
					"version": 1,
					"entities": [{"id": "cup", "label": "the cup"}],
					"relations": [],
					"events": [
						{
							"id": "lift",
							"description": "The subject lifts the cup.",
							"start": 0,
							"end": 2,
							"after": [],
						}
					],
					"checks": [
						{
							"id": "grip",
							"scope": "event",
							"event": "lift",
							"claim": "The grip remains attached.",
						}
					],
				},
			}
		)
		prompt = compile_h3(shot, self.project())
		self.assertEqual(prompt.count("The subject lifts the cup."), 1)
		self.assertIn("0-2s only: The grip remains attached.", prompt)
		shot.motion_plan_json["scene_contract"]["transitions"] = [
			{
				"event": "lift",
				"before": "The cup rests on its support",
				"during": "The grip supports the cup as it rises",
				"after": "The supported cup is visibly raised",
				"forbidden": "The cup floats independently of the grip",
			}
		]
		for prompt in [
			compile_h3(shot, self.project()),
			compile_segment_prompt_from_snapshot(shot, self.project(), 1, 1),
		]:
			self.assertIn("The grip supports the cup as it rises", prompt)
			self.assertIn("The supported cup is visibly raised", prompt)
			self.assertIn("The cup floats independently of the grip", prompt)

	@patch("joymedia.services.planning.prompts._mood", return_value="Warm side light.")
	@patch("joymedia.services.planning.prompts.first_frame_inventory", return_value="the subject")
	@patch("joymedia.services.planning.prompts._character_names", return_value=[])
	@patch("joymedia.services.planning.prompts.keep_rules", return_value="")
	def test_style_appears_once_and_existing_printed_artwork_is_preserved(self, keep, names, inventory, mood):
		shot = self.shot(references=[{"reference_role": "general", "asset_version": "REF"}])
		prompt = compile_h3(shot, self.project())
		self.assertEqual(prompt.count("Warm side light."), 1)
		self.assertIn("Preserve existing printed quantities", prompt)
		self.assertNotIn("Never print quantities", prompt)

	def test_camera_ignores_storyboard_camera_prose_but_preserves_actions(self):
		s = self.shot()
		s.generation_prompt = "The woman lifts the cup. Camera: fast orbit and zoom."
		before = camera_plan(s, self.project())
		s.generation_prompt = "A glass falls. Camera: whip pan."
		self.assertEqual(before, camera_plan(s, self.project()))
		self.assertEqual(
			_without_camera("The woman lifts the cup. The camera zooms in."), "The woman lifts the cup."
		)
		self.assertIn(
			'"The camera moves."', _without_camera('The woman says "The camera moves." The camera zooms in.')
		)
		self.assertEqual(
			_without_camera("A woman lifts a cup. Barely perceptible slow dolly-in only."),
			"A woman lifts a cup.",
		)

	@patch("joymedia.services.planning.prompts._mood", return_value="Cinematic.")
	def test_segment_never_replays_an_earlier_action(self, mood):
		s = self.shot()
		s.generation_prompt = "Open the door then lift the cup."
		s.motion_plan_json = {
			"actions": [
				{"start": 0, "end": 5, "action": "Open the door"},
				{"start": 5, "end": 10, "action": "Lift the cup"},
			]
		}
		s.duration_seconds = 10
		p = compile_h3(
			s,
			self.project(),
			segment_index=2,
			segment_count=2,
			segment_start_frame=120,
			segment_effective_frames=120,
		)
		self.assertIn("0-5s: Lift the cup", p)
		self.assertNotIn("Open the door", p)
		self.assertIn("without restarting", p)
		self.assertIn("The camera holds one static shot", p)

	@patch("joymedia.services.planning.prompts._mood", return_value="Cinematic.")
	def test_effects_only_strips_music_and_spoken_audio(self, mood):
		s = self.shot()
		s.generation_prompt = "The woman lifts the cup.\n\nAudio: cup tap; music: piano; singing and speech."
		p = compile_h3(s, self.project(soundtrack_mode="Sound effects only"))
		self.assertTrue(p.endswith("non_diegetic_music: N/A"))
		self.assertNotIn("piano", p)
		self.assertIn("cup tap", p)
		self.assertIn("no speech", p)

	def test_structural_preservation_and_final_hold_override_motion(self):
		s = self.shot()
		s.motion_plan_json = {"camera_motion": "locked"}
		self.assertEqual(camera_plan(s, self.project())["behavior"], "locked")
		s.motion_plan_json = {}
		s.references = [{"reference_role": "product"}, {"reference_role": "person"}]
		s.shot_number = 2
		self.assertEqual(camera_plan(s, self.project())["behavior"], "locked")
		s.references = []
		self.assertEqual(camera_plan(s, self.project(), is_final=True)["behavior"], "locked")
		s.shot_number = 2
		self.assertEqual(camera_plan(s, self.project())["behavior"], "locked")
		self.assertEqual(
			camera_plan(
				s,
				self.project(),
				framing_safety={"status": "assessed", "complete": True, "bounds": [0.15, 0.15, 0.85, 0.85]},
			)["behavior"],
			"push_in",
		)

	@patch("joymedia.services.planning.prompts._mood", return_value="Cinematic.")
	def test_last_frame_alignment_is_only_declared_when_present(self, mood):
		s = self.shot()
		s.references = [{"reference_role": "last_frame", "asset_version": "LAST"}]
		with patch("joymedia.services.planning.prompts._identity_guard", return_value="Reference fidelity."):
			p = compile_h3(s, self.project())
		self.assertIn("5.00-second mark", p)
		self.assertIn("Picture 2", p)
		s.references = []
		p = compile_h3(s, self.project())
		self.assertNotIn("Picture 2", p)

	@patch("joymedia.services.planning.prompts._mood", return_value="Cinematic.")
	def test_dispatch_uses_executable_node_type_and_leaves_images_alone(self, mood):
		w = frappe._dict(workflow_json={"104": {"class_type": "MiniMaxH3ImageToVideo"}})
		self.assertEqual(h3_kind(w), "image")
		s = self.shot()
		s.image_prompt = "One cup on a table."
		p = compile_segment_prompt_from_snapshot(s, self.project(), 1, 1, workflow=w)
		self.assertIn("integrated_multimodal_description:", p)
		self.assertEqual(
			compile_segment_prompt_from_snapshot(s, self.project(), 1, 1, prompt_source="image", workflow=w),
			"One cup on a table.",
		)
		self.assertNotIn(
			"integrated_multimodal_description:",
			compile_segment_prompt_from_snapshot(s, self.project(), 1, 1),
		)

	@patch("joymedia.services.planning.prompts._mood", return_value="Cinematic.")
	def test_named_dialogue_audio_stays_out_of_the_soundscape(self, mood):
		s = self.shot()
		s.generation_prompt = "The woman lifts the cup.\n\nAudio: SFX: a cup tap; Dialogue: Maya (S1) says: <d>[English] Take the morning; keep it yours.</d>; music: slow guitar."
		p = compile_h3(s, self.project())
		visual, sound = p.split("overall_soundscape:")
		self.assertIn("<d>[English] Take the morning; keep it yours.</d>", visual)
		self.assertNotIn("Take the morning", sound)
		self.assertNotIn("No spoken dialogue", visual)

	def test_inline_camera_removal_keeps_the_subject_action(self):
		self.assertEqual(
			_without_camera("The camera follows her as she lifts the cup."), "she lifts the cup."
		)
		self.assertEqual(
			_without_camera("The woman lifts the cup while the camera zooms in."), "The woman lifts the cup."
		)

	@patch("joymedia.services.planning.prompts._mood", return_value="Cinematic.")
	def test_physical_contract_is_clipped_to_continuation_window(self, mood):
		s = self.shot()
		s.duration_seconds = 10
		s.motion_plan_json = {
			"scene_contract": {
				"version": 1,
				"entities": [{"id": "actor", "label": "the woman"}],
				"relations": [],
				"events": [
					{"id": "first", "description": "open the door", "start": 0, "end": 4, "after": []},
					{"id": "second", "description": "lift the cup", "start": 5, "end": 9, "after": ["first"]},
				],
			}
		}
		p = compile_h3(
			s,
			self.project(),
			segment_index=2,
			segment_count=2,
			segment_start_frame=120,
			segment_effective_frames=120,
		)
		self.assertIn("0-4s: lift the cup", p)
		self.assertNotIn("0-4s: open the door", p)

	@patch("joymedia.services.planning.prompts._mood", return_value="Cinematic.")
	def test_reference_format_does_not_pretend_the_library_was_uploaded(self, mood):
		p = compile_h3(self.shot(), self.project(), kind="reference")
		self.assertTrue(p.startswith("subject_definitions:"))
		self.assertIn("detailed_description: [Shot 1]", p)
		self.assertNotIn("Picture 2", p)
		self.assertNotIn("Video 1", p)

	@patch("joymedia.services.planning.prompts._mood", return_value="Cinematic.")
	def test_preformatted_h3_input_has_one_set_of_output_fields(self, mood):
		s = self.shot()
		s.generation_prompt = "integrated_multimodal_description: [Shot 1] A woman lifts a cup.\n\noverall_soundscape: A soft cup tap.\n\nnon_diegetic_music: Sparse piano at slow tempo."
		p = compile_h3(s, self.project())
		for field in ["integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:"]:
			self.assertEqual(p.count(field), 1)
		self.assertIn("A woman lifts a cup.", p)
		self.assertIn("Sparse piano at slow tempo.", p)

	def test_legacy_closing_camera_cannot_conflict_with_the_final_hold(self):
		from joymedia.services.planning.director_rules import CLOSING_DIRECTION

		self.assertNotIn("camera", _without_camera(CLOSING_DIRECTION).lower())

	@patch("joymedia.services.planning.prompts._mood", return_value="Cinematic.")
	def test_multiple_internal_shots_require_separate_storyboard_scenes(self, mood):
		s = self.shot()
		s.generation_prompt = "integrated_multimodal_description: [Shot 1] Walk. [Shot 2] Turn.\n\noverall_soundscape: Footsteps.\n\nnon_diegetic_music: N/A"
		with self.assertRaisesRegex(ValueError, "separate storyboard scene"):
			compile_h3(s, self.project())

	def test_tight_or_unknown_frame_never_authorizes_push_in(self):
		from joymedia.services.planning.framing import allows_push

		for report in [
			None,
			{},
			{"status": "unknown"},
			{"status": "assessed", "complete": True, "bounds": [0, 0.2, 1, 0.8]},
			{"status": "assessed", "complete": False, "bounds": [0.15, 0.15, 0.85, 0.85]},
		]:
			self.assertFalse(allows_push(report))
			self.assertEqual(
				camera_plan(self.shot(), self.project(), framing_safety=report)["behavior"], "locked"
			)

	def test_camera_motion_does_not_alternate_by_shot_number(self):
		s = self.shot()
		safety = {"status": "assessed", "complete": True, "bounds": [0.15, 0.15, 0.85, 0.85]}
		for i in range(1, 7):
			s.shot_number = i
			self.assertEqual(camera_plan(s, self.project(), framing_safety=safety)["behavior"], "push_in")

	def test_bounded_push_in_has_a_numeric_limit_and_final_hold(self):
		p = camera_plan(
			self.shot(),
			self.project(),
			framing_safety={"status": "assessed", "complete": True, "bounds": [0.15, 0.15, 0.85, 0.85]},
		)
		self.assertIn("at most 2 percent", p["direction"])
		self.assertIn("holds the final composition", p["direction"])


class TestOpeningFrameAssessment(FrappeTestCase):
	def test_grounded_pixel_bounds_are_normalized_and_cached_by_image(self):
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from types import SimpleNamespace

		from PIL import Image

		from joymedia.services.planning.framing import allows_push, inspect_framing

		with TemporaryDirectory() as tmp:
			root = Path(tmp)
			image = root / "frame.png"
			Image.new("RGB", (200, 400), "white").save(image)
			version = SimpleNamespace(name="V", file="/private/files/frame.png")
			file = SimpleNamespace(get_full_path=lambda: str(image))
			with (
				patch(
					"frappe.get_doc",
					side_effect=lambda kind, *a: version if kind == "Asset Version" else file,
				),
				patch("frappe.get_site_path", side_effect=lambda *a: str(root / "cache" / a[-1])),
				patch("joymedia.services.runtime.endpoints.is_configured", return_value=True),
				patch(
					"joymedia.services.runtime.endpoints.endpoint",
					return_value=frappe._dict(model="vision", revision="test"),
				),
				patch(
					"joymedia.services.review.consistency.ask",
					return_value={
						"bbox_2d": [20, 40, 180, 360],
						"complete": True,
						"reason": "Subject has visible space around it.",
					},
				) as ask,
			):
				report = inspect_framing(
					frappe._dict(references=[{"reference_role": "first_frame", "asset_version": "V"}])
				)
				self.assertEqual(report["bounds"], [0.1, 0.1, 0.9, 0.9])
				self.assertTrue(allows_push(report))
				inspect_framing(
					frappe._dict(references=[{"reference_role": "first_frame", "asset_version": "V"}])
				)
				self.assertEqual(ask.call_count, 1)
				Image.new("RGB", (200, 400), "blue").save(image)
				inspect_framing(
					frappe._dict(references=[{"reference_role": "first_frame", "asset_version": "V"}])
				)
				self.assertEqual(ask.call_count, 2)
