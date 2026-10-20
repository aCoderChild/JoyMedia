from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning.prompts import (
	compile_prompt_for_documents,
	compile_segment_prompt_from_snapshot,
)


class TestPromptCompiler(FrappeTestCase):
	def test_an_explicit_scene_reset_overrides_the_project_continuity_default(self):
		project = frappe._dict(generation_mode="Continuous", global_instructions="")
		shot = frappe._dict(name="SHOT-TEST", shot_number=2, generation_prompt="A new action.", continuity_mode="New Scene")
		prompt = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertNotIn("previous shot's generated last frame", prompt)
		shot.continuity_mode = "Continue"
		self.assertIn("previous shot's generated last frame", compile_prompt_for_documents(shot, project, prompt_source="motion"))

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
		self.assertIn("show only the intended reference subjects and assets", prompt)
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
	def test_a_project_without_a_sound_mode_gets_sound_effects_only(self):
		shot = frappe._dict(
			name="S", shot_number=1, image_prompt="A bear.", references=[], handoff_type="", end_state="",
			generation_prompt="The bear pulls tissue.\n\nAudio: sound effects: rip.", motion_plan_json="{}",
		)
		prompt = compile_prompt_for_documents(shot, frappe._dict(generation_mode="Multi-shot", global_instructions=""), prompt_source="motion")
		self.assertIn("no background music", prompt)
		self.assertIn("no speech", prompt)

	def test_the_audio_paragraph_ends_the_video_prompt_after_all_other_text(self):
		shot = frappe._dict(
			name="S", shot_number=1, image_prompt="A bear.", references=[{"asset_version": "AV"}], handoff_type="", end_state="",
			generation_prompt="The bear pulls tissue.\n\nAudio: sound effects: rip, rip, rip.",
			motion_plan_json='{"actions": [{"start": 0, "end": 3, "action": "pulls tissue"}]}',
		)
		project = frappe._dict(generation_mode="Multi-shot", global_instructions="", soundtrack_mode="Full soundtrack")
		prompt = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertTrue(prompt.endswith("Audio: sound effects: rip, rip, rip."))
		self.assertEqual(1, prompt.count("Audio:"))
		self.assertIn("Identity consistency", prompt)

	def test_a_prompt_without_sound_direction_is_unchanged(self):
		from joymedia.services.planning.prompts import _audio_line_last

		self.assertEqual("One.\n\nTwo.", _audio_line_last("One.\n\nTwo."))

	def test_sound_effects_only_drops_music_and_rules_out_speech(self):
		from joymedia.services.planning.prompts import NO_VOICE_OR_MUSIC, _audio_line_last

		result = _audio_line_last("Audio: sound effects: pop; music: jazz.\n\nMore.", sound_effects_only=True)
		self.assertEqual(f"More.\n\nAudio: sound effects: pop at 2.5s; silence between the sounds. {NO_VOICE_OR_MUSIC}", result)
		# With no effect cue left, do not invent sounds for unrelated products.
		self.assertEqual(
			f"Mother pours milk.\n\nAudio: silence. {NO_VOICE_OR_MUSIC}",
			_audio_line_last("Mother pours milk.\n\nAudio: music: jazz.", sound_effects_only=True),
		)

	def test_sound_effects_only_drops_a_vocal_sentence_of_a_cue(self):
		from joymedia.services.planning.prompts import NO_VOICE_OR_MUSIC, _audio_line_last

		result = _audio_line_last("Audio: sound effects: Paper tearing. Baby giggling laughter.", sound_effects_only=True)
		self.assertEqual(f"Audio: sound effects: Paper tearing at 2.5s; silence between the sounds. {NO_VOICE_OR_MUSIC}", result)

	def test_references_ask_for_identity_and_marks_not_for_label_text(self):
		from joymedia.services.planning.prompts import compile_prompt_for_documents

		shot = frappe._dict(
			name="S", shot_number=1, generation_prompt="A scene.", image_prompt="", references=[{"reference_role": "Product"}]
		)
		prompt = compile_prompt_for_documents(shot, {}, prompt_source="image")
		self.assertIn("artwork and marks", prompt)
		self.assertIn("unreadable texture", prompt)
		self.assertNotIn("every visible logo or label", prompt)

	def test_the_cast_is_named_so_reference_subjects_resolve_consistently(self):
		from joymedia.services.planning.prompts import compile_prompt_for_documents

		shot = frappe._dict(
			name="S", shot_number=1, generation_prompt="Mother bear pulls tissue with her hand.", image_prompt="", motion_plan_json="",
			handoff_type="", end_state="", references=[{"reference_role": "Character", "asset_version": "AV1"}],
		)
		project = frappe._dict(
			generation_mode="Multi-shot", global_instructions="", references=[{"asset_version": "AV1", "label": "Shera mascot"}]
		)
		with patch("joymedia.services.keyframes.overlay.describe_colours", return_value="mostly cream"):
			prompt = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertIn("The only character in this scene is Shera mascot (mostly cream", prompt)
		self.assertIn("keep exactly these colours", prompt)
		self.assertIn("every visible limb belongs to it", prompt)

	def test_every_segment_of_a_long_scene_carries_the_cast_and_the_audio_rules(self):
		from joymedia.services.planning.prompts import compile_segment_prompt_from_snapshot

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
			with patch("joymedia.services.keyframes.overlay.describe_colours", return_value="mostly cream"):
				prompt = compile_segment_prompt_from_snapshot(shot, project, index, 2, fps=24, segment_start_frame=0, segment_effective_frames=48)
			self.assertIn("The only character in this scene is Shera mascot", prompt)
			self.assertIn("Add no text, letters", prompt)
			self.assertIn("first frame is the truth for the place, the lighting", prompt)
			self.assertTrue(prompt.split("\n\n")[-1].startswith("Audio:"), prompt[-300:])

	def test_a_mother_and_a_kid_are_kept_apart(self):
		from joymedia.services.planning.prompts import compile_prompt_for_documents

		shot = frappe._dict(
			name="S", shot_number=1, generation_prompt="Mother lifts the paper while the baby watches.", image_prompt="",
			motion_plan_json="", handoff_type="", end_state="", references=[
				{"reference_role": "Character", "asset_version": "AV1"}, {"reference_role": "Character", "asset_version": "AV2"},
			],
		)
		project = frappe._dict(generation_mode="Multi-shot", global_instructions="", references=[
			{"asset_version": "AV1", "label": "Gấu mẹ (mother mascot)"}, {"asset_version": "AV2", "label": "Gấu con (kid mascot)"},
		])
		with patch("joymedia.services.keyframes.overlay.describe_colours", return_value=""):
			prompt = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertIn("different individuals", prompt)
		self.assertNotIn("Gấu", prompt.split("Identity consistency")[-1])
		self.assertIn("at most a very slight, slow push-in", prompt)
		self.assertIn("In the text, a mother, mom, mum, mommy, mama is the mother character; a kid, kids, child, children, baby is the kid character", prompt)

	def test_quantities_and_quoted_words_are_not_sent_to_the_video_model(self):
		from joymedia.services.planning.prompts import _scrub_printable

		self.assertEqual(
			"Products beside the product pack. The mother says.",
			_scrub_printable('Products in the centre beside the big box (30 packs per box). The mother says "Buy now".'),
		)

	def test_placement_phrases_are_not_sent_to_the_video_model(self):
		from joymedia.services.planning.prompts import _scrub_printable

		self.assertEqual(
			"The mother winks and gives a thumbs up.",
			_scrub_printable("The mother winks and gives a thumbs up at the top right corner of the frame."),
		)
		self.assertEqual("The kid sits.", _scrub_printable("The kid sits on the left side of the screen."))

	def test_the_prompt_lists_what_the_first_frame_contains(self):
		from joymedia.services.planning.prompts import first_frame_inventory

		shot = frappe._dict(references=[
			{"reference_role": "Character", "asset_version": "AV1"}, {"reference_role": "Character", "asset_version": "AV2"},
			{"reference_role": "Product", "asset_version": "AV3"}, {"reference_role": "Product", "asset_version": "AV4"},
			{"reference_role": "Logo", "asset_version": "AV5"},
		], shot_number=1)
		project = frappe._dict(references=[
			{"asset_version": "AV1", "label": "Gấu mẹ (mother mascot)"}, {"asset_version": "AV2", "label": "Gấu con (kid mascot)"},
		], shots=[{"shot_number": 1}, {"shot_number": 2}])
		with patch("joymedia.services.keyframes.overlay.describe_colours", return_value=""):
			# The logo is not in any frame: it is laid over the finished film.
			self.assertEqual(
				"from left to right the mother character and the kid character, beside them 2 approved product assets",
				first_frame_inventory(shot, project),
			)
			shot.shot_number = 2
			self.assertIn("the approved product assets, large, in the centre", first_frame_inventory(shot, project))

	def test_boxes_become_the_product_packs_and_zooms_are_removed(self):
		from joymedia.services.planning.prompts import _scrub_printable

		self.assertEqual(
			"The kid pulls tissue from the product pack. The mother winks.",
			_scrub_printable(
				"The kid pulls tissue from the large box. The mother winks at top right corner. "
				"The camera slowly zooms in on emotional expressions."
			),
		)

	def test_the_segments_of_a_long_scene_are_scrubbed_in_their_text_and_their_action_plan(self):
		from joymedia.services.planning.prompts import compile_segment_prompt_from_snapshot

		shot = frappe._dict(
			name="S", shot_number=1, generation_prompt="The kid pulls tissue from the large box (30 packs per box).",
			image_prompt="", handoff_type="", end_state="", references=[{"reference_role": "Character", "asset_version": "AV1"}],
			motion_plan_json='{"actions":[{"start":0,"end":7,"action":"Camera zooms in. The mother winks at top right corner."}]}',
		)
		project = frappe._dict(generation_mode="Multi-shot", global_instructions="", references=[{"asset_version": "AV1", "label": "Mascot"}])
		with patch("joymedia.services.keyframes.overlay.describe_colours", return_value=""), patch(
			"joymedia.services.planning.prompts._scrub_options", return_value={"packaging": True, "zoom": True}
		):
			prompt = compile_segment_prompt_from_snapshot(shot, project, 1, 2, fps=24, segment_start_frame=0, segment_effective_frames=124)
		movement = prompt.split("Identity consistency")[0].split("The first frame contains")[0]
		for unwanted in ("30 packs", "large box", "zooms", "top right"):
			self.assertNotIn(unwanted, movement)

	def test_draw_mode_uses_the_reviewed_still_and_ties_each_character_to_its_picture(self):
		from joymedia.services.planning.prompts import compile_prompt_for_documents

		shot = frappe._dict(
			name="S", shot_number=1, image_prompt="The mother holds a cookie beside one intact glass. The kid watches from the floor.",
			generation_prompt="The mother lifts a glass of milk. The kid sits on the floor. Then she pours. Camera: Close-up of the table.\n\nAudio: sound effects: pour.",
			setting_prompt="A warm wooden kitchen.", character_mode="Draw in scene",
			references=[
				{"reference_role": "Character", "asset_version": "AV1"}, {"reference_role": "Character", "asset_version": "AV2"},
				{"reference_role": "Environment", "asset_version": "AV-ROOM"},
			],
		)
		project = frappe._dict(references=[
			{"asset_version": "AV1", "label": "Gấu mẹ (mother mascot, flower on head)"}, {"asset_version": "AV2", "label": "Gấu con (kid mascot)"},
		])
		with patch("joymedia.services.keyframes.overlay.describe_colours", return_value="mostly cream"):
			prompt = compile_prompt_for_documents(shot, project, prompt_source="image")
		self.assertTrue(prompt.startswith("Close-up of the table. The mother holds a cookie beside one intact glass. The kid watches from the floor."), prompt)
		self.assertNotIn("lifts a glass of milk", prompt)
		self.assertNotIn("Then she pours", prompt)
		self.assertIn("mother mascot, flower on head is the character of picture 1 (mostly cream; pale, light colouring, never brown or tan), with the build of a mother: a full-grown adult", prompt)
		self.assertIn("kid mascot is the character of picture 2 (mostly cream; pale, light colouring, never brown or tan), with the build of a kid: about half an adult's height", prompt)
		self.assertIn("not the pose or objects in their reference image", prompt)
		self.assertIn("The place: A warm wooden kitchen, the room of picture 3: the same furniture, window and light.", prompt)
		self.assertNotIn("Audio", prompt)

	def test_a_planned_image_description_is_made_safe_for_drawing(self):
		from joymedia.services.planning.prompts import _scrub_for_drawing

		self.assertEqual(
			"medium shot on hand pulling out tissue. Full box of Shera appearing beside the kid.",
			_scrub_for_drawing("Macro super close-up on hand pulling out tissue. Full box of 30 packs of Shera appearing beside the kid."),
		)

	def test_a_parent_and_a_child_are_told_their_relative_size(self):
		from joymedia.services.planning.prompts import _size_sentence

		self.assertEqual(
			"Scale matters: the kid mascot is much smaller: the mother mascot is about 2.5 times taller, stands upright on two "
			"legs and towers over the kid mascot, who comes up only to the mother mascot's waist. ",
			_size_sentence([("the mother mascot", 1.0), ("the kid mascot", 0.4)]),
		)
		self.assertEqual("", _size_sentence([("a", 1.0), ("b", 0.95)]))
		self.assertEqual("", _size_sentence([("a", 1.0)]))

	def test_a_box_shaped_product_keeps_its_box_and_a_zoom_stays_unless_a_product_is_pasted(self):
		from joymedia.services.planning.prompts import _scrub_options, _scrub_printable

		shot = frappe._dict(references=[{"reference_role": "Product", "asset_version": "AV1"}])
		project = frappe._dict(references=[{"asset_version": "AV1", "label": "Cereal box"}])
		with patch("joymedia.services.keyframes.overlay._cutout_path", return_value=None):
			options = _scrub_options(shot, project)
		self.assertEqual({"packaging": False, "zoom": False}, options)
		self.assertEqual(
			"She opens the box. The camera slowly zooms in.", _scrub_printable("She opens the box. The camera slowly zooms in.", **options)
		)
		with patch("joymedia.services.keyframes.overlay._cutout_path", return_value="/p.png"):
			project = frappe._dict(references=[{"asset_version": "AV1", "label": "Tissue pack"}])
			self.assertEqual({"packaging": False, "zoom": True}, _scrub_options(shot, project))

	def test_an_unknown_character_mode_never_overrides_the_projects(self):
		from joymedia.services.project.context import _valid_character_mode

		self.assertEqual("Draw in scene", _valid_character_mode("Draw in scene"))
		self.assertIsNone(_valid_character_mode("\\nDraw in scene\\nPaste exact art"))
		self.assertIsNone(_valid_character_mode(""))
		self.assertIsNone(_valid_character_mode(None))

	def test_similes_and_texture_words_do_not_reach_the_video_model(self):
		from joymedia.services.planning.prompts import _scrub_printable

		self.assertEqual(
			"The mother presses a tissue to the kid's cheek. The kid laughs with eyes closed.",
			_scrub_printable(
				"The mother presses a tissue to the kid's cheek. The kid laughs with eyes closed as if leaning into "
				"the fluffy cloud-like fur of the mother."
			),
		)
		self.assertEqual("It is soft.", _scrub_printable("It is soft, like a cloud."))


class TestCameraDirection(FrappeTestCase):
	def test_explicit_locked_camera_never_receives_the_default_push_in(self):
		from joymedia.services.planning.prompts import _identity_guard, camera_moves

		for plan in ('{"camera_motion":"locked"}', {"camera_motion": "locked"}):
			shot = frappe._dict(
				generation_prompt="Camera: Slow zoom in.", references=[], motion_plan_json=plan,
			)
			self.assertFalse(camera_moves(shot))
			guard = _identity_guard(shot, frappe._dict(references=[]))
			self.assertIn("The camera stays completely still", guard)
			self.assertNotIn("allow at most a very slight", guard)
			self.assertNotIn("Follow the camera direction", guard)

	def test_a_moving_camera_in_the_sheet_is_recognised(self):
		from joymedia.services.planning.prompts import camera_moves

		moving = ("X. Camera: Wide to medium shot.", "X. Camera: Top-down (overhead) -> Extreme close-up.", "X. Camera: Slow zoom in.")
		still = ("X. Camera: Close-up of the table. Slow-motion.", "X. Camera: Eye-level medium shot.", "No camera line.")
		for text in moving:
			self.assertTrue(camera_moves(frappe._dict(generation_prompt=text)), text)
		for text in still:
			self.assertFalse(camera_moves(frappe._dict(generation_prompt=text)), text)


class TestOpeningFraming(FrappeTestCase):
	def test_the_first_frame_opens_on_the_start_of_the_sheets_camera_direction(self):
		from joymedia.services.planning.prompts import opening_framing

		def framing(camera):
			return opening_framing(frappe._dict(generation_prompt=f"The kid spills juice. Camera: {camera}\n\nAudio: a splash."))

		self.assertEqual("Close-up of family dining table", framing("Close-up of family dining table. Slow-motion."))
		self.assertEqual("Wide shot", framing("Wide shot to close-up."))
		self.assertEqual("Top-down", framing("Top-down -> Macro close-up"))
		# An extreme close-up opens as a medium shot, so the characters are seen acting.
		self.assertEqual("medium shot of the pack", framing("Extreme close-up of the pack."))
		self.assertEqual("wide establishing shot", opening_framing(frappe._dict(generation_prompt="The kid spills juice.")))
		self.assertEqual("medium shot", opening_framing(frappe._dict(shot_number=2, generation_prompt="The kid spills juice.")))


class TestProductIdentity(FrappeTestCase):
	def test_the_product_is_described_without_brand_or_numbers(self):
		from joymedia.services.planning import prompts

		frappe.cache.delete_value(f"joymedia:product_identity:{prompts.hashlib.sha1('Khăn giấy rút Shera (300 tờ)'.encode()).hexdigest()}")
		with patch("joymedia.services.planning.production.translate", return_value="Shera pull-out tissues (300 sheets"):
			text = prompts.product_identity(frappe._dict(product_name="Khăn giấy rút Shera (300 tờ)"))
		self.assertTrue(text.startswith("The advertised product is pull-out tissues. "))
		self.assertNotIn("Shera", text)
		self.assertNotIn("300", text)
		# A scene without a referenced product receives no inferred category-specific rule.
		with patch("joymedia.services.planning.production.translate", return_value="Shera pull-out tissues (300 sheets"):
			self.assertEqual("", prompts.product_identity(frappe._dict(product_name="Khăn giấy rút Shera (300 tờ)"), shows=False))
		with patch("joymedia.services.planning.production.translate", return_value="Sparkling orange juice"):
			self.assertEqual("The advertised product is Sparkling orange juice. ", prompts.product_identity(frappe._dict(product_name="Nước cam có ga X1")))


class TestSplitScreenPrompt(FrappeTestCase):
	def test_the_panels_stay_apart_and_in_place_and_the_inventory_names_a_pack_per_panel(self):
		import json

		from joymedia.services.planning.prompts import _split_screen_rule, first_frame_inventory

		shot = frappe._dict(views_json=json.dumps([{"text": "A"}, {"text": "B"}, {"text": "C"}]),
			references=[{"reference_role": "Product", "asset_version": "AV-PACK"}], generation_prompt="Split screen.")
		self.assertIn("3 panels stacked top to bottom", _split_screen_rule(shot))
		self.assertIn("nothing moves from one panel into another", _split_screen_rule(shot))
		self.assertEqual("", _split_screen_rule(frappe._dict(views_json="")))
		self.assertIn("in each of the 3 stacked panels, the approved product asset in its middle", first_frame_inventory(shot, frappe._dict(references=[])))


class TestSheetBrief(FrappeTestCase):
	def test_the_briefs_tone_usp_and_character_lines_reach_the_prompts(self):
		import json

		from joymedia.services.planning import prompts

		metadata = {"tone_mood": "Dễ thương, ấm áp", "usp": "Siêu mềm. Không mủn khi gặp nước", "characters": "- Gấu trắng con\n- Gấu trắng mẹ - nhân vật chính"}
		english = {"Dễ thương, ấm áp": "Cute, warm", "Siêu mềm. Không mủn khi gặp nước": "super soft, does not tear when wet",
			"Gấu trắng con": "White bear cub", "Gấu trắng mẹ - nhân vật chính": "White bear mother - the main character",
			"Khăn giấy Shera": "Shera tissues"}
		for text in english:
			frappe.cache.delete_value(f"joymedia:sheet_english:{prompts.hashlib.sha1(text.encode()).hexdigest()}")
		frappe.cache.delete_value(f"joymedia:product_identity:{prompts.hashlib.sha1('Khăn giấy Shera'.encode()).hexdigest()}")
		source = json.dumps({"selected_demo": {"metadata": metadata}})
		with patch.object(frappe.db, "get_value", return_value=source), \
			patch("joymedia.services.planning.production.translate", side_effect=lambda text, project, about="": english[text]):
			project = frappe._dict(name="PRJ-X", product_name="Khăn giấy Shera")
			brief = prompts.sheet_brief(project)
			self.assertEqual({"child": "White bear cub", "mother": "White bear mother - the main character"}, brief["characters"])
			self.assertEqual("Mood: Cute, warm. ", prompts._mood(project))
			# A selling point is not drawn: a drawing model would print it as text in the picture.
			self.assertEqual("The advertised product is tissues. ", prompts.product_identity(project))


class TestReferenceDescriptions(FrappeTestCase):
	def test_a_vietnamese_description_is_translated_and_a_place_never_shows_what_must_not_be_shown(self):
		from joymedia.services.planning import prompts

		with patch.object(prompts, "_english", side_effect=lambda text, project: {"Thân tròn màu kem": "a round cream body"}.get(text, text)):
			self.assertEqual("the mascot: a round cream body", prompts._describe_character("Gấu Shera (Thân tròn màu kem)", frappe._dict()))
		self.assertEqual("mother mascot", prompts._describe_character("Gấu mẹ (mother mascot)"))
		with patch.object(prompts, "sheet_brief", return_value={"tone": "", "style": "3D animation", "avoid": "water vanishing instantly"}):
			self.assertEqual("Visual style: 3D animation. Never show: water vanishing instantly. ", prompts._mood(frappe._dict()))


class TestCastNames(FrappeTestCase):
	def test_a_character_without_a_family_role_is_the_mascot_and_its_poses_are_the_same_mascot(self):
		from joymedia.services.planning import prompts

		one = frappe._dict(references=[
			{"label": "Gấu Shera (kem)", "reference_role": "Character"}, {"label": "Gấu Shera ôm tim (ôm tim)", "reference_role": "Character"},
			{"label": "Giấy Shera", "reference_role": "Product"},
		])
		self.assertEqual("the mascot", prompts.cast_name("Gấu Shera ôm tim (ôm tim)", one))
		self.assertEqual("the mascot", prompts.cast_name("Gấu Shera (kem)", one))
		two = frappe._dict(references=[{"label": "Gấu Shera", "reference_role": "Character"}, {"label": "Mèo Mimi", "reference_role": "Character"}])
		self.assertEqual(("mascot 1", "mascot 2"), (prompts.cast_name("Gấu Shera", two), prompts.cast_name("Mèo Mimi", two)))
		self.assertEqual("the mother character", prompts.cast_name("Gấu mẹ", two))  # a family role still names it
		self.assertEqual("the person", prompts.cast_name("Chị Lan", frappe._dict(references=[{"label": "Chị Lan", "reference_role": "Person"}]), person=True))

	def test_a_settings_subject_clause_is_dropped_and_the_room_kept(self):
		from joymedia.services.keyframes.overlay import DEFAULT_SETTING, usable_setting

		self.assertEqual(
			"A warm room with a table, on the table a plate of cookies, a glass of water.",
			usable_setting("A warm room with a table; on the table a plate of cookies, a glass of water, and a pack of Shera paper."),
		)
		self.assertEqual("White and blue background.", usable_setting("White and blue background."))
		self.assertEqual(DEFAULT_SETTING, usable_setting("A mascot waving."))

	def test_the_products_name_keeps_no_quantity_or_separator(self):
		from joymedia.services.planning import prompts

		frappe.cache.delete_value(prompts._translation_key("product_identity", "GIẤY LỤA RÚT SHERA 400 TỜ / 4 LỚP"))
		with patch("joymedia.services.planning.production.translate", return_value="SHERA PULL-OUT TISSUE 400 SHEETS / 4 LAYERS"), \
			patch.object(prompts, "sheet_brief", return_value={"usp": ""}):
			self.assertTrue(prompts.product_identity(frappe._dict(product_name="GIẤY LỤA RÚT SHERA 400 TỜ / 4 LỚP")).startswith("The advertised product is pull-out tissue."))


class TestCompositedArtworkPrompt(FrappeTestCase):
	def test_model_does_not_draw_objects_supplied_by_compositor(self):
		from joymedia.services.planning.prompts import _with_opening_staging

		plan = {"scene_contract": {"version":1, "entities":[{"id":"actor","label":"the actor"},{"id":"product","label":"the original product"}], "counts":[{"entity":"actor","count":1},{"entity":"product","count":1}]}, "artwork_placements":[{"asset_version":"SOURCE","entity":"product","box":[.1,.2,.3,.4]}]}
		before = frappe.as_json(plan)
		text = _with_opening_staging("Draw the actor and empty surface.", frappe._dict(motion_plan_json=plan, duration_seconds=4))
		self.assertIn("the actor", text)
		self.assertNotIn("the original product", text)
		self.assertEqual(before, frappe.as_json(plan))


class TestClipBoundaries(FrappeTestCase):
	def test_handoff_does_not_ask_video_model_to_render_next_shot(self):
		from joymedia.services.planning.prompts import temporal_timing_instruction

		shot = frappe._dict(motion_plan_json={"actions": [{"start": 0, "end": 3, "action": "Lift the vase."}]}, handoff_type="motion_continuation", end_state="vase raised")
		text = temporal_timing_instruction(shot)
		self.assertIn("Finish in this state: vase raised", text)
		self.assertIn("Do not cut, transition or begin another shot", text)
		self.assertNotIn("Continue as", text)
		self.assertIn("Conclude the whole film", temporal_timing_instruction(shot, is_final=True))


class TestBodyPartsBelongToTheCast(FrappeTestCase):
	def test_multiple_actors_do_not_assign_every_unowned_limb_to_first_reference(self):
		from joymedia.services.planning.prompts import scene_actor

		shot = frappe._dict(references=[{"reference_role": "Person", "asset_version": "A"}, {"reference_role": "Person", "asset_version": "B"}])
		project = frappe._dict(references=[{"asset_version": "A", "label": "Alice", "identity_key": "a"}, {"asset_version": "B", "label": "Bob", "identity_key": "b"}])
		self.assertIsNone(scene_actor(shot, project))

	def test_an_unowned_hand_is_the_actors_own_and_an_owned_one_is_left(self):
		from joymedia.services.planning.prompts import owned_body_parts

		self.assertEqual(
			"Close-up of hand belonging to the mascot + table. The mascot raises its paw.",
			owned_body_parts("Close-up of hand + table. The mascot raises its paw.", "the mascot"),
		)
		self.assertEqual("Both rounded paws belonging to the actor touch.", owned_body_parts("Both rounded paws touch.", "the actor"))
		self.assertEqual("its own short rounded paw", owned_body_parts("its own short rounded paw", "the actor"))
		self.assertEqual("Close-up of hand.", owned_body_parts("Close-up of hand.", None))  # no cast, nothing to own it

	def test_object_supports_and_prohibited_anatomy_keep_their_meaning(self):
		from joymedia.services.planning.prompts import owned_body_parts

		for text in (
			"The table has four corner legs reaching the floor.",
			"Chair arms support the seated actor; clock hands indicate noon.",
			"No human hands or fingers. Never add external arms.",
			"A hand belonging to Alice holds the vase.",
			"Feet of the cabinet stay on the floor.",
		):
			self.assertEqual(text, owned_body_parts(text, "the actor"))
		text = owned_body_parts("Both rounded paws touch.", "the actor")
		self.assertEqual(text, owned_body_parts(text, "the actor"))

	def test_a_scene_with_a_cast_forbids_strangers(self):
		from joymedia.services.planning import prompts

		shot = frappe._dict(references=[{"reference_role": "Character", "asset_version": "AV1"}])
		project = frappe._dict(references=[{"asset_version": "AV1", "label": "Gấu Shera", "reference_role": "Character"}])
		self.assertIn("never bare human skin or human fingers", prompts._no_outsiders(shot, project))
		self.assertTrue(prompts._no_outsiders(shot, project).startswith("The mascot is the one doing the action"))


class TestOverlayTextStaysOutOfPictures(FrappeTestCase):
	def test_directions_to_show_words_logos_and_calls_to_action_never_reach_the_models(self):
		from joymedia.services.planning import prompts

		text = ("The pack stands next to the mascot, who waves. Display the logo, '400 SHEETS • 4 LAYERS', message, and "
			"purchase invitation. Hold the frame stable. Text overlays added in post-production.")
		scrubbed = prompts._scrub_printable(text)
		self.assertIn("The pack stands next to the mascot, who waves.", scrubbed)
		self.assertIn("Hold the frame stable.", scrubbed)
		for gone in ("Display", "logo", "400", "invitation", "overlays"):
			self.assertNotIn(gone, scrubbed)
		self.assertNotIn("logo", prompts._scrub_for_drawing(text))
		# A scene that shows the product keeps its action.
		self.assertEqual("The mascot shows the paper to the camera.", prompts.without_overlay_text("The mascot shows the paper to the camera."))
		# The editor's notes go too, even as prohibitions: naming text and logos makes a video model paint them.
		self.assertEqual("Keep the pack's shape.", prompts.without_overlay_text(
			"Keep the pack's shape. Use the standard packaging image, do not let AI rewrite the logo or specifications; the text overlay in post-production."))
