from unittest.mock import patch
import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.prompt_compiler import (
	_build_source_snapshot, compile_prompt_for_documents, compile_segment_prompt_from_snapshot, segment_action_timing_instruction,
)
from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter


class TestPromptCompiler(FrappeTestCase):
	def test_segment_timing_contract_is_model_agnostic(self):
		instruction = segment_action_timing_instruction()
		self.assertIn("seconds-based", instruction)
		self.assertNotIn("frame 110", instruction)
		self.assertEqual(instruction, segment_action_timing_instruction())

	def test_source_snapshot_uses_current_media_and_shot_fields(self):
		project = frappe._dict(
			name="PROJECT-TEST",
			generation_mode="Multi-shot",
			global_instructions="",
		)
		shot = frappe._dict(
			name="SHOT-TEST",
			generation_prompt="A premium bottle reveal with a slow dolly-in.",
		)

		snapshot = _build_source_snapshot(shot, project)

		self.assertEqual(
			{
				"media_project": "PROJECT-TEST",
				"shot": "SHOT-TEST",
				"generation_prompt": "A premium bottle reveal with a slow dolly-in.",
				"image_prompt": "",
				"motion_plan_json": "",
				"start_state": "",
				"end_state": "",
				"handoff_type": "",
				"global_instructions": "",
			},
			snapshot,
		)
		self.assertNotIn("required_elements", snapshot)

		prompt = GenericComfyUIAdapter().compile_prompt(shot, project)

		self.assertEqual(prompt, "A premium bottle reveal with a slow dolly-in.")

	def test_image_and_motion_stages_compile_their_own_prompts(self):
		project = frappe._dict(generation_mode="Continuous", global_instructions="")
		shot = frappe._dict(
			name="SHOT-TEST", shot_number=1, generation_prompt="The hand lifts the bottle toward camera.",
			image_prompt="Compose the bottle on a marble table.",
			motion_plan_json='{"actions":[{"start":0,"end":4,"action":"lift the bottle"},{"start":4,"end":5,"action":"hold the pose"}]}',
			end_state="bottle held toward camera", handoff_type="pose_transition",
		)
		image = compile_prompt_for_documents(shot, project, prompt_source="image")
		motion = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertEqual(image, "Compose the bottle on a marble table.")
		self.assertIn("The hand lifts the bottle", motion)
		self.assertNotIn("Compose the bottle on a marble table.", motion)
		self.assertIn("0-4s: lift the bottle", motion)

	def test_referenced_product_prompts_require_fidelity(self):
		project = frappe._dict(generation_mode="Multi-shot", global_instructions="")
		shot = frappe._dict(
			name="SHOT-TEST", shot_number=1,
			generation_prompt="A presenter holds the product toward camera.",
			references=[{"reference_role": "product", "asset_version": "ASTV-TEST"}],
		)
		prompt = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertIn("show only the intended referenced product", prompt)
		self.assertIn("do not swap, merge, deform", prompt)

	def test_continuation_only_receives_its_own_action_window(self):
		project = frappe._dict(references=[], generation_mode="Multi-shot", global_instructions="")
		shot = frappe._dict(
			name="SHOT-TEST", shot_number=1, generation_prompt="A presenter tours the property.",
			motion_plan_json='{"actions":[{"start":0,"end":5,"action":"show the lobby"},{"start":5,"end":10,"action":"walk into the pool area"}]}',
			end_state="pool area visible", handoff_type="ending", references=[],
		)

		prompt = compile_segment_prompt_from_snapshot(
			shot, project, 2, 2, segment_start_frame=120, segment_effective_frames=120, fps=24, is_final=True,
		)

		self.assertIn("0-5s: walk into the pool area", prompt)
		self.assertNotIn("show the lobby", prompt)

	def test_a_keyframe_image_prompt_never_receives_segment_or_action_text(self):
		project = frappe._dict(references=[], generation_mode="Multi-shot", global_instructions="")
		shot = frappe._dict(
			name="SHOT-TEST", shot_number=1, generation_prompt="Video.", image_prompt="A bright room.",
			motion_plan_json='{"actions":[{"start":0,"end":5,"action":"the bear gives a thumbs up"}]}',
			end_state="thumbs up", handoff_type="ending", references=[],
		)

		prompt = compile_segment_prompt_from_snapshot(shot, project, 1, 2, prompt_source="image", fps=24)

		self.assertEqual("A bright room.", prompt)


class TestIdentityConsistency(FrappeTestCase):
	def _shot(self, references):
		return frappe._dict(
			name="S", shot_number=1, generation_prompt="The bear tips the glass.", image_prompt="A bear at a table.",
			references=references, motion_plan_json="", handoff_type="", end_state="",
		)

	def _project(self):
		return frappe._dict(generation_mode="Multi-shot", global_instructions="")

	def test_the_video_prompt_keeps_characters_as_in_the_first_frame(self):
		prompt = compile_prompt_for_documents(self._shot([{"asset_version": "AV"}]), self._project(), prompt_source="motion")
		self.assertIn("Identity consistency", prompt)
		self.assertIn("including close-ups", prompt)

	def test_the_keyframe_prompt_and_reference_free_shots_do_not_get_it(self):
		self.assertNotIn(
			"Identity consistency",
			compile_prompt_for_documents(self._shot([{"asset_version": "AV"}]), self._project(), prompt_source="image"),
		)
		self.assertNotIn(
			"Identity consistency", compile_prompt_for_documents(self._shot([]), self._project(), prompt_source="motion")
		)


class TestAudioLineLast(FrappeTestCase):
	def test_the_audio_paragraph_ends_the_video_prompt_after_all_other_text(self):
		shot = frappe._dict(
			name="S", shot_number=1, image_prompt="A bear.", references=[{"asset_version": "AV"}], handoff_type="", end_state="",
			generation_prompt="The bear pulls tissue.\n\nAudio: sound effects: rip, rip, rip.",
			motion_plan_json='{"actions": [{"start": 0, "end": 3, "action": "pulls tissue"}]}',
		)
		prompt = compile_prompt_for_documents(shot, frappe._dict(generation_mode="Multi-shot", global_instructions=""), prompt_source="motion")
		self.assertTrue(prompt.endswith("Audio: sound effects: rip, rip, rip."))
		self.assertEqual(1, prompt.count("Audio:"))
		self.assertIn("Identity consistency", prompt)

	def test_a_prompt_without_sound_direction_is_unchanged(self):
		from joymedia.services.prompt_compiler import _audio_line_last

		self.assertEqual("One.\n\nTwo.", _audio_line_last("One.\n\nTwo."))

	def test_sound_effects_only_drops_music_and_rules_out_speech(self):
		from joymedia.services.prompt_compiler import NO_VOICE_OR_MUSIC, _audio_line_last

		result = _audio_line_last("Audio: sound effects: pop; music: jazz.\n\nMore.", sound_effects_only=True)
		self.assertEqual(f"More.\n\nAudio: sound effects: pop at 2.5s; silence between the sounds. {NO_VOICE_OR_MUSIC}", result)
		# With no effect cue left, the sounds of the scene's own action are described instead.
		self.assertEqual(
			"Mother pours milk.\n\nAudio: a soft paper rustle at 0.8s, a light tap at 2.5s, a gentle crinkle at 4.2s; "
			f"silence between the sounds. {NO_VOICE_OR_MUSIC}",
			_audio_line_last("Mother pours milk.\n\nAudio: music: jazz.", sound_effects_only=True),
		)

	def test_sound_effects_only_drops_a_vocal_sentence_of_a_cue(self):
		from joymedia.services.prompt_compiler import NO_VOICE_OR_MUSIC, _audio_line_last

		result = _audio_line_last("Audio: sound effects: Paper tearing. Baby giggling laughter.", sound_effects_only=True)
		self.assertEqual(f"Audio: sound effects: Paper tearing at 2.5s; silence between the sounds. {NO_VOICE_OR_MUSIC}", result)

	def test_references_ask_for_shape_colour_mascot_and_logo_not_for_label_text(self):
		from joymedia.services.prompt_compiler import compile_prompt_for_documents

		shot = frappe._dict(
			name="S", shot_number=1, generation_prompt="A scene.", image_prompt="", references=[{"reference_role": "Product"}]
		)
		prompt = compile_prompt_for_documents(shot, {}, prompt_source="image")
		self.assertIn("mascot artwork and brand logo", prompt)
		self.assertIn("unreadable texture", prompt)
		self.assertNotIn("every visible logo or label", prompt)

	def test_the_cast_is_named_so_bears_and_hands_resolve_to_the_mascot(self):
		from joymedia.services.prompt_compiler import compile_prompt_for_documents

		shot = frappe._dict(
			name="S", shot_number=1, generation_prompt="Mother bear pulls tissue with her hand.", image_prompt="", motion_plan_json="",
			handoff_type="", end_state="", references=[{"reference_role": "Character", "asset_version": "AV1"}],
		)
		project = frappe._dict(
			generation_mode="Multi-shot", global_instructions="", references=[{"asset_version": "AV1", "label": "Shera mascot"}]
		)
		with patch("joymedia.services.subject_overlay.describe_colours", return_value="mostly cream"):
			prompt = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertIn("The only character in this scene is Shera mascot (mostly cream", prompt)
		self.assertIn("keep exactly these colours", prompt)
		self.assertIn("every hand, arm or paw is its own", prompt)

	def test_every_segment_of_a_long_scene_carries_the_cast_and_the_audio_rules(self):
		from joymedia.services.prompt_compiler import compile_segment_prompt_from_snapshot

		shot = frappe._dict(
			name="S", shot_number=1, generation_prompt="Mother bear pulls tissue.\n\nAudio: sound effects: paper tearing.",
			image_prompt="", motion_plan_json="", handoff_type="", end_state="",
			references=[{"reference_role": "Character", "asset_version": "AV1"}],
		)
		project = frappe._dict(
			generation_mode="Multi-shot", global_instructions="", soundtrack_mode="Sound effects only",
			references=[{"asset_version": "AV1", "label": "Shera mascot"}],
		)
		for index in (1, 2):
			with patch("joymedia.services.subject_overlay.describe_colours", return_value="mostly cream"):
				prompt = compile_segment_prompt_from_snapshot(shot, project, index, 2, fps=24, segment_start_frame=0, segment_effective_frames=48)
			self.assertIn("The only character in this scene is Shera mascot", prompt)
			self.assertIn("Add no text, letters", prompt)
			self.assertIn("first frame is the truth for the place, the lighting", prompt)
			self.assertTrue(prompt.split("\n\n")[-1].startswith("Audio:"), prompt[-300:])

	def test_a_mother_and_a_kid_are_kept_apart(self):
		from joymedia.services.prompt_compiler import compile_prompt_for_documents

		shot = frappe._dict(
			name="S", shot_number=1, generation_prompt="Mother lifts the paper while the baby watches.", image_prompt="",
			motion_plan_json="", handoff_type="", end_state="", references=[
				{"reference_role": "Character", "asset_version": "AV1"}, {"reference_role": "Character", "asset_version": "AV2"},
			],
		)
		project = frappe._dict(generation_mode="Multi-shot", global_instructions="", references=[
			{"asset_version": "AV1", "label": "Gấu mẹ (mother mascot)"}, {"asset_version": "AV2", "label": "Gấu con (kid mascot)"},
		])
		with patch("joymedia.services.subject_overlay.describe_colours", return_value=""):
			prompt = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertIn("different individuals", prompt)
		self.assertNotIn("Gấu", prompt.split("Identity consistency")[-1])
		self.assertIn("at most a very slight, slow push-in", prompt)
		self.assertIn("A mother, mom or mama named in the text is the mother mascot; a baby, kid, child or cub named in the text is the kid mascot", prompt)

	def test_quantities_and_quoted_words_are_not_sent_to_the_video_model(self):
		from joymedia.services.prompt_compiler import _scrub_printable

		self.assertEqual(
			"Products beside the product pack. The mother says.",
			_scrub_printable('Products in the centre beside the big box (30 packs per box). The mother says "Buy now".'),
		)

	def test_placement_phrases_are_not_sent_to_the_video_model(self):
		from joymedia.services.prompt_compiler import _scrub_printable

		self.assertEqual(
			"The mother winks and gives a thumbs up.",
			_scrub_printable("The mother winks and gives a thumbs up at the top right corner of the frame."),
		)
		self.assertEqual("The kid sits.", _scrub_printable("The kid sits on the left side of the screen."))

	def test_the_prompt_lists_what_the_first_frame_contains(self):
		from joymedia.services.prompt_compiler import first_frame_inventory

		shot = frappe._dict(references=[
			{"reference_role": "Character", "asset_version": "AV1"}, {"reference_role": "Character", "asset_version": "AV2"},
			{"reference_role": "Product", "asset_version": "AV3"}, {"reference_role": "Product", "asset_version": "AV4"},
			{"reference_role": "Logo", "asset_version": "AV5"},
		])
		project = frappe._dict(references=[
			{"asset_version": "AV1", "label": "Gấu mẹ (mother mascot)"}, {"asset_version": "AV2", "label": "Gấu con (kid mascot)"},
		])
		with patch("joymedia.services.subject_overlay.describe_colours", return_value=""):
			self.assertEqual(
				"from left to right the mother mascot and the kid mascot, in front of them 2 small product packs, "
				"the brand logo at the top left",
				first_frame_inventory(shot, project),
			)

	def test_boxes_become_the_product_packs_and_zooms_are_removed(self):
		from joymedia.services.prompt_compiler import _scrub_printable

		self.assertEqual(
			"The kid pulls tissue from the product pack. The mother winks.",
			_scrub_printable(
				"The kid pulls tissue from the large box. The mother winks at top right corner. "
				"The camera slowly zooms in on emotional expressions."
			),
		)

	def test_the_segments_of_a_long_scene_are_scrubbed_in_their_text_and_their_action_plan(self):
		from joymedia.services.prompt_compiler import compile_segment_prompt_from_snapshot

		shot = frappe._dict(
			name="S", shot_number=1, generation_prompt="The kid pulls tissue from the large box (30 packs per box).",
			image_prompt="", handoff_type="", end_state="", references=[{"reference_role": "Character", "asset_version": "AV1"}],
			motion_plan_json='{"actions":[{"start":0,"end":7,"action":"Camera zooms in. The mother winks at top right corner."}]}',
		)
		project = frappe._dict(generation_mode="Multi-shot", global_instructions="", references=[{"asset_version": "AV1", "label": "Mascot"}])
		with patch("joymedia.services.subject_overlay.describe_colours", return_value=""):
			prompt = compile_segment_prompt_from_snapshot(shot, project, 1, 2, fps=24, segment_start_frame=0, segment_effective_frames=124)
		movement = prompt.split("Identity consistency")[0].split("The first frame contains")[0]
		for unwanted in ("30 packs", "large box", "zooms", "top right"):
			self.assertNotIn(unwanted, movement)

	def test_draw_mode_names_the_place_then_the_action_then_human_behaviour(self):
		from joymedia.services.prompt_compiler import compile_prompt_for_documents

		shot = frappe._dict(
			name="S", shot_number=1, image_prompt="Macro close-up of a hand.",
			generation_prompt="The mother lifts a glass of milk. The kid sits on the floor. Then she pours.\n\nAudio: sound effects: pour.",
			setting_prompt="A warm wooden kitchen.", character_mode="Draw in scene",
			references=[{"reference_role": "Character", "asset_version": "AV1"}, {"reference_role": "Character", "asset_version": "AV2"}],
		)
		project = frappe._dict(references=[
			{"asset_version": "AV1", "label": "Gấu mẹ (mother mascot, flower on head)"}, {"asset_version": "AV2", "label": "Gấu con (kid mascot)"},
		])
		prompt = compile_prompt_for_documents(shot, project, prompt_source="image")
		self.assertTrue(prompt.startswith("A warm wooden kitchen. The mother lifts a glass of milk. The kid sits on the floor."))
		self.assertNotIn("Then she pours", prompt)
		self.assertIn("act exactly like human people", prompt)
		self.assertIn("mother mascot, flower on head; kid mascot", prompt)
		self.assertNotIn("Audio", prompt)

	def test_a_planned_image_description_is_made_safe_for_drawing_mascots(self):
		from joymedia.services.prompt_compiler import _scrub_for_drawing

		self.assertEqual(
			"medium shot on paw pulling out tissue. Full box of Shera appearing beside the kid.",
			_scrub_for_drawing("Macro super close-up on hand pulling out tissue. Full box of 30 packs of Shera appearing beside the kid."),
		)
