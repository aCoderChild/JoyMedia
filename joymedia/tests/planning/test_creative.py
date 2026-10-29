import copy
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from redis.exceptions import LockError

from joymedia.services.planning.creative import script_workbook, validate_script
from joymedia.services.planning.grounding import grounded_contract


def sample_script():
	return {
		"title": "A moving product",
		"logline": "A character moves the product, then presents it.",
		"format": "16:9",
		"format_reason": "Room for lateral action",
		"duration_seconds": 10,
		"visual_style": "Warm directional light with layered depth",
		"music": "Bright acoustic percussion, brisk tempo",
		"features": ["Blue exterior"],
		"scenes": [
			{
				"beat_name": "Movement",
				"duration_seconds": 6,
				"visual_camera": "A product on a wooden table.",
				"action": "[0-1s] Grip the product.\n[1-6s] Move it along the table.",
				"visible_change": "Product left -> product right",
				"cast": [],
				"products": ["product"],
				"place": "Warm studio with a wooden table",
				"continuity_rules": "Keep the product supported.",
				"shot_framing": "medium",
				"shot_angle": "eye_level",
				"narrative_stage": "present",
				"voice_over": "",
				"audio_cues": "Soft contact",
				"on_screen_text": "",
			},
			{
				"beat_name": "Resolve",
				"duration_seconds": 4,
				"visual_camera": "Blue product, directional light.",
				"action": "[0-2s] Turn the product to face forward.\n[2-4s] Hold the final view.",
				"visible_change": "Side -> front",
				"cast": [],
				"products": ["product"],
				"place": "Warm studio with a wooden table",
				"continuity_rules": "Preserve its dimensions.",
				"shot_framing": "close_up",
				"shot_angle": "eye_level",
				"narrative_stage": "hero",
				"voice_over": "",
				"audio_cues": "Soft cloth",
				"on_screen_text": "See more",
			},
		],
	}


def _streamed(content):
	"""A planner response as vLLM streams it: one content delta, then [DONE]."""
	response = MagicMock(ok=True)
	response.iter_lines.return_value = [
		"data: " + json.dumps({"choices": [{"delta": {"content": content}}]}),
		"",
		"data: [DONE]",
	]
	return response


class TestOpeningTextCrossCheck(TestCase):
	def test_supplied_product_view_is_visible_without_qualifying_a_missing_angle(self):
		from joymedia.api.creative import _prepared_assets

		project = frappe._dict(
			selected_media=[frappe._dict(reference_key="product", asset_version="original")]
		)
		with (
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_doc", return_value=project),
			patch("frappe.db.get_value", return_value="/private/files/product.jpg"),
		):
			assets = _prepared_assets(
				{
					"project": "test",
					"product_views": [
						{"source": "product", "view": "front", "status": "supplied"},
						{"source": "product", "view": "back", "status": "source_locked"},
					],
				}
			)
		self.assertEqual("/private/files/product.jpg", assets[0]["url"])
		self.assertEqual("supplied", assets[0]["status"])
		self.assertIsNone(assets[1]["url"])
		self.assertEqual("source_locked", assets[1]["status"])

	def test_parallel_planners_do_not_prepare_the_same_video_twice(self):
		from joymedia.services.generation.creative_batch import prepare_batch

		@contextmanager
		def occupied_lock(*args, **kwargs):
			raise LockError("already held")
			yield

		with (
			patch("joymedia.services.generation.creative_batch.frappe.cache") as cache,
			patch("joymedia.services.generation.creative_batch._prepare_batch_locked") as prepare,
		):
			cache.lock.side_effect = occupied_lock
			self.assertIsNone(prepare_batch("CRB-00001", 0))
			prepare.assert_not_called()
			cache.lock.assert_called_once_with(
				"joymedia-creative-prepare:CRB-00001:0", timeout=10800, blocking_timeout=0
			)

	def test_cinematic_opening_keeps_a_broad_product_action_moving(self):
		from joymedia.services.planning.camera import infer_cinematic_intent

		intent = infer_cinematic_intent(
			{"stage": "grip", "framing": "wide", "subject_motion": "manipulation"}, opening=True
		)
		self.assertEqual(
			{"behavior": "push_in", "purpose": "hook", "energy": "brisk", "allow_reframe": False}, intent
		)

	def test_automatic_delivery_keeps_deferred_director_notes_without_stopping(self):
		from joymedia.services.generation.creative_batch import (
			_automatic_script_defects,
			_blocking_script_defects,
		)

		self.assertEqual(
			[],
			_automatic_script_defects(
				{
					"director_notes": ["Scene 1: Acquire the product before use."],
					"writer_fallback": {"quality_review": "deferred"},
				}
			),
		)
		self.assertEqual(
			["Scene 1: Acquire the product before use."],
			_automatic_script_defects({"director_notes": ["Scene 1: Acquire the product before use."]}),
		)
		self.assertEqual(
			["Show the spill first."],
			_blocking_script_defects(
				{
					"writer_fallback": {"quality_review": "deferred"},
					"action_review": {
						"issues": [
							{
								"category": "missing_prerequisite",
								"instruction": "Show the spill first.",
							}
						]
					},
				}
			),
		)

	def test_multiple_unresolved_critical_frames_request_new_concept(self):
		from joymedia.services.generation.creative_batch import _critical_frame_defects

		shots = [
			frappe._dict(
				shot_number=1,
				consistency_status="Needs Review",
				consistency_notes="Critical geometry: duplicate actor",
			),
			frappe._dict(
				shot_number=2,
				consistency_status="Needs Review",
				consistency_notes="Physical staging review: uncertain",
			),
			frappe._dict(
				shot_number=3,
				consistency_status="Needs Review",
				consistency_notes="Critical prop: extra package",
			),
		]
		self.assertEqual(2, len(_critical_frame_defects(shots)))
		self.assertEqual([], _critical_frame_defects(shots[:2]))
		self.assertEqual(
			1,
			len(
				_critical_frame_defects(
					[
						frappe._dict(
							shot_number=4,
							consistency_status="Needs Review",
							consistency_notes="Critical prop: paper or tissue sheet has an implausible material",
						)
					]
				)
			),
		)

	def test_identity_drift_is_a_frame_correction(self):
		from joymedia.services.generation.creative_batch import _frame_corrections, _scene_repair_notes

		shot = frappe._dict(
			name="SHOT-IDENTITY",
			consistency_status="Needs Review",
			consistency_notes="Critical identity: character eye design changed from the original reference",
		)
		self.assertEqual({shot.name: [shot.consistency_notes]}, _frame_corrections([shot]))
		shot.shot_number = 1
		shot.consistency_notes = (
			"Critical identity: selected generated character view has stale or missing pose qualification"
		)
		self.assertEqual({}, _frame_corrections([shot]))
		self.assertIn("Never reuse an unqualified pose", _scene_repair_notes([shot])[0]["text"])

	def test_automatic_delivery_restarts_with_the_rejected_script_as_history(self):
		from joymedia.services.generation.creative_batch import _restart_automatic_script_variant

		variant = {
			"project": "PRJ-OLD",
			"workbook": "/private/old.xlsx",
			"script": sample_script(),
			"title": "Old concept",
			"plans": [{"shot": "SHOT-1"}],
			"keyframe_request": {"run": "RUN-1"},
			"status": "Planning",
			"nonce": "old",
		}
		self.assertTrue(
			_restart_automatic_script_variant(
				variant,
				sample_script(),
				["Scene 1: Replace the unsupported spill."],
			)
		)
		self.assertEqual("Queued", variant["status"])
		self.assertEqual(1, variant["automatic_script_redraws"])
		self.assertNotIn("project", variant)
		self.assertEqual("PRJ-OLD", variant["history"][0]["project"])
		self.assertEqual(sample_script(), variant["history"][0]["script"])
		self.assertIn("unsupported spill", str(variant["revision"]["notes"]))
		empty_child = {"project": "PRJ-TEXT-ONLY", "status": "Planning", "nonce": "first"}
		self.assertTrue(
			_restart_automatic_script_variant(empty_child, sample_script(), ["Scene 2 needs a new action."])
		)
		self.assertEqual("PRJ-TEXT-ONLY", empty_child["project"])

	def test_ambiguous_generated_product_can_redraw_with_a_new_seed(self):
		from joymedia.services.generation.creative_batch import _nonretryable_scene_failure

		attempt = frappe._dict(
			status="Failed",
			failure_class="Input",
			error_summary="One of the selected media inputs is not usable for this scene.",
			error_details="Reference preparation was rejected. Expected one unambiguous product; detected 2.",
		)
		with patch("frappe.get_all", side_effect=[[frappe._dict(name="TASK-1", shot="SHOT-1")], [attempt]]):
			self.assertIsNone(_nonretryable_scene_failure("RUN-1", ["SHOT-1"]))
		attempt.error_details = "Product view is incompatible with the supplied source photograph."
		with patch("frappe.get_all", side_effect=[[frappe._dict(name="TASK-1", shot="SHOT-1")], [attempt]]):
			self.assertIsNone(_nonretryable_scene_failure("RUN-1", ["SHOT-1"]))
		attempt.error_details = "The immutable reference file changed."
		with patch("frappe.get_all", side_effect=[[frappe._dict(name="TASK-1", shot="SHOT-1")], [attempt]]):
			self.assertEqual("SHOT-1", _nonretryable_scene_failure("RUN-1", ["SHOT-1"])["shot"])

	def test_camera_review_requires_quoted_camera_direction_in_action(self):
		from joymedia.services.planning.script_review import _filter_unsubstantiated_camera_issues

		script = sample_script()
		script["scenes"][1]["action"] = "[0-4s] The product remains on the table."
		findings = {
			"issues": [
				{
					"scene": 2,
					"category": "camera_in_action",
					"quote": "The product remains on the table.",
				},
				{
					"scene": 1,
					"category": "camera_in_action",
					"quote": "The camera pushes in.",
				},
			]
		}
		script["scenes"][0]["action"] += " The camera pushes in."
		self.assertEqual(
			["The camera pushes in."],
			[row["quote"] for row in _filter_unsubstantiated_camera_issues(findings, script)["issues"]],
		)

	def test_unproven_opening_conflict_does_not_block_the_script(self):
		from joymedia.services.planning.script_review import _cross_check_opening

		script = sample_script()
		script["scenes"][0]["visual_camera"] = "The actor stands near the table."
		script["scenes"][0]["action"] = "[0-1s] The actor walks toward the table and grips the product."
		finding = {
			"scene": 1,
			"category": "opening_mismatch",
			"quote": "walks toward the table",
			"instruction": "Start closer.",
		}
		with patch(
			"joymedia.services.planning.production._ask_planner",
			return_value={
				"opening_quote": "stands near the table",
				"action_quote": "walks toward the table",
				"contradiction": False,
			},
		):
			result = _cross_check_opening({"issues": [finding]}, script)
		self.assertEqual("production_detail", result["issues"][0]["category"])
		self.assertFalse(result["issues"][0]["text_cross_check"]["physical_qualification"])

	def test_hallucinated_retraction_preserves_original_issue(self):
		from joymedia.services.planning.script_review import _cross_check_opening

		finding = {
			"scene": 1,
			"category": "opening_mismatch",
			"quote": "Grip the product",
			"instruction": "Fix pose.",
		}
		with patch(
			"joymedia.services.planning.production._ask_planner",
			return_value={
				"opening_quote": "product floats in air",
				"action_quote": "Grip the product",
				"contradiction": False,
			},
		):
			result = _cross_check_opening({"issues": [finding]}, sample_script())
		self.assertEqual("opening_mismatch", result["issues"][0]["category"])
		self.assertIn("absent", result["issues"][0]["cross_check_error"])


class TestGeneratedScriptValidation(TestCase):
	def test_distinct_operations_do_not_repeat_their_result_presentation(self):
		from joymedia.services.planning.creative import story_logic_errors

		self.assertIsNone(
			story_logic_errors(
				[
					{"action": "The mascot folds the tissue, then unfolds it, showing the crease."},
					{"action": "The mascot sets the tissue back on the floor, showing the softness."},
					{"action": "The original product remains still."},
				]
			)
		)
		for repeated in ("examine the tissue", "show the tissue"):
			self.assertIn(
				"repeat",
				story_logic_errors(
					[
						{"action": "The mascot will " + repeated + "."},
						{"action": "Then the mascot will " + repeated + "."},
						{"action": "The original product remains still."},
					]
				),
			)

	def test_identical_adjacent_actions_are_detected_without_product_vocabulary(self):
		from joymedia.services.planning.creative import story_logic_errors

		scenes = [
			{"action": "[0-1s] Model holds the garment up. [1-2s] Model turns it."},
			{"action": "[0-0.5s] Model holds the garment up. [0.5-2s] Model turns it."},
			{"action": "Present the product."},
		]
		self.assertIn("Scenes 1 and 2 repeat", story_logic_errors(scenes))
		scenes[1]["action"] = "Model touches the garment's fabric."
		self.assertIsNone(story_logic_errors(scenes))

	def test_explicit_shot_count_is_enforced_before_advisory_fallback(self):
		with self.assertRaisesRegex(ValueError, "requests 5 shots"):
			validate_script(
				{"scenes": [{}, {}, {}, {}, {}, {}, {}]},
				[],
				{"creative_direction": "Make five shots with distinct opening poses."},
				[],
			)

	def test_hyphenated_shot_count_in_brief_is_enforced(self):
		with self.assertRaisesRegex(ValueError, "requests 5 shots"):
			validate_script(
				{"scenes": [{}, {}, {}, {}, {}, {}, {}]},
				[],
				{
					"creative_direction": "Automatically write a coherent five-shot screenplay in the standard template."
				},
				[],
			)

	def test_carried_pack_cannot_teleport_back_to_table(self):
		from joymedia.services.planning.creative import _validate_product_support_continuity

		scenes = [
			{
				"visual_camera": "The pack starts on the coffee table.",
				"action": "[0-2s] Bear picks up the tissue pack.",
			},
			{"visual_camera": "Bear holds the pack.", "action": "[0-2s] Bear opens the pack."},
			{
				"visual_camera": "The pack rests on the coffee table.",
				"action": "[0-2s] The pack remains still.",
			},
		]
		with self.assertRaisesRegex(ValueError, "without a visible placement"):
			_validate_product_support_continuity(scenes)
		scenes[1]["action"] += "\n[2-3s] Bear places the pack on the coffee table."
		_validate_product_support_continuity(scenes)

	def test_later_extraction_cannot_follow_use_of_the_same_item(self):
		from joymedia.services.planning.creative import _later_acquisition_conflict

		self.assertEqual(
			(1, 2, "tissue"),
			_later_acquisition_conflict(
				[
					{"action": "The mascot presses a white tissue against the table."},
					{"action": "The mascot lifts an edge of the tissue from the pack."},
				]
			),
		)
		self.assertEqual(
			(1, 2, "shirt"),
			_later_acquisition_conflict(
				[
					{"action": "The model wears the shirt on the street."},
					{"action": "The model removes the shirt from its parcel."},
				]
			),
		)
		self.assertIsNone(
			_later_acquisition_conflict(
				[
					{"action": "The mascot presses the tissue pack against the table."},
					{"action": "The mascot lifts an edge of the tissue from the pack."},
				]
			)
		)
		self.assertIsNone(
			_later_acquisition_conflict(
				[
					{"action": "The mascot presses a tissue against the table."},
					{"action": "The mascot takes another tissue from the pack."},
				]
			)
		)

	inventory: ClassVar = [{"key": "product", "role": "Product"}]
	constraints: ClassVar = {"duration_seconds": 10, "aspect_ratio": "16:9"}

	def test_thirty_second_workflow_uses_frame_capacity_without_padding_scenes(self):
		from joymedia.services.planning.creative import script_schema

		schema = script_schema(
			self.inventory,
			{"duration_seconds": 30, "aspect_ratio": "9:16", "fps": 24, "max_scene_frames": 124},
		)
		# 30 s needs 6 full shots; planning at 85% of a shot leaves room for rhythm: 7 scenes.
		self.assertEqual(7, schema["properties"]["scenes"]["minItems"])
		action_rule = schema["properties"]["scenes"]["items"]["properties"]["action"]["description"]
		self.assertIn("Combine approach/reach with acquisition", action_rule)

	def test_automatic_duration_freezes_scene_contract_after_first_proposal(self):
		from joymedia.services.planning.creative import _freeze_proposed_duration, script_schema

		constraints = {"duration_seconds": None, "aspect_ratio": "16:9", "fps": 24, "max_scene_frames": 124}
		schema = script_schema(self.inventory, constraints)
		self.assertEqual(2, schema["properties"]["scenes"]["minItems"])
		_freeze_proposed_duration(constraints, schema, {"duration_seconds": 35})
		self.assertEqual(35, constraints["duration_seconds"])
		self.assertEqual({"const": 35}, schema["properties"]["duration_seconds"])
		self.assertEqual(8, schema["properties"]["scenes"]["minItems"])
		_freeze_proposed_duration(constraints, schema, {"duration_seconds": 10})
		self.assertEqual(35, constraints["duration_seconds"])
		short = {"duration_seconds": None, "aspect_ratio": "16:9", "fps": 24, "max_scene_frames": 124}
		short_schema = script_schema(self.inventory, short)
		_freeze_proposed_duration(short, short_schema, {"duration_seconds": 30, "scenes": [{}, {}, {}, {}]})
		self.assertEqual(int(4 * 124 * 0.85) / 24, short["duration_seconds"])
		self.assertEqual(4, short_schema["properties"]["scenes"]["minItems"])

	def test_frame_capacity_error_names_required_and_supplied_scene_counts(self):
		from joymedia.services.planning.creative import fit_generated_timing

		script = sample_script()
		with self.assertRaisesRegex(ValueError, "needs at least 7 scenes.*received 2"):
			fit_generated_timing(script, 35, 24, max_scene_frames=124)

	def test_passive_opening_requires_an_object_action(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The mascot sits and looks at the product."
		with self.assertRaisesRegex(ValueError, "opening cannot consist only"):
			validate_script(script, self.inventory, self.constraints)

	def test_adjacent_shots_cannot_pick_up_the_same_held_object_twice(self):
		from joymedia.services.planning.creative import _validate_action_progress

		scenes = [
			{"action": "[0-5s] The mascot picks up the pack and presses it.", "duration_seconds": 5},
			{"action": "[0-5s] The mascot picks up the pack and rotates it.", "duration_seconds": 5},
			{"action": "[0-5s] The product rests on the table.", "duration_seconds": 5},
		]
		with self.assertRaisesRegex(ValueError, "acquires the same object again"):
			_validate_action_progress(scenes)

	def test_visible_liquid_cause_counts_as_material_action(self):
		from joymedia.services.planning.creative import _validate_action_progress

		_validate_action_progress(
			[
				{"action": "[0-3s] A cup tips over and spills water onto the table.", "duration_seconds": 3},
				{"action": "[0-3s] The tissue contacts and blots the water.", "duration_seconds": 3},
				{"action": "[0-3s] The pack is presented.", "duration_seconds": 3},
			]
		)

	def test_preparatory_reach_cannot_consume_an_entire_action_shot(self):
		script = sample_script()
		inventory = [*self.inventory, {"key": "mascot", "role": "Character"}]
		script["scenes"][0]["cast"] = ["mascot"]
		for action in (
			"[0-6s] The mascot reaches toward the product.",
			"[0-6s] The mascot reaches toward the table where the product is placed.",
		):
			with (
				self.subTest(action=action),
				self.assertRaisesRegex(ValueError, "no completed object or material action"),
			):
				script["scenes"][0]["action"] = action
				validate_script(script, inventory, self.constraints)
		script["scenes"][0]["action"] = (
			"[0-1s] The mascot reaches toward the product.\n[1-6s] The mascot grips and lifts the product."
		)
		self.assertEqual(script, validate_script(script, inventory, self.constraints))
		script["scenes"][0]["action"] = "[0-6s] The mascot grasps the product with both paws."
		self.assertEqual(script, validate_script(script, inventory, self.constraints))

	def test_middle_reaction_shot_requires_product_progress(self):
		script = sample_script()
		middle = copy.deepcopy(script["scenes"][0])
		middle["duration_seconds"] = 1
		middle["action"] = "[0-1s] The mascot looks at the product and smiles."
		second = copy.deepcopy(script["scenes"][0])
		second["duration_seconds"] = 1
		second["action"] = "[0-1s] The mascot turns the product to the side."
		script["scenes"][0]["duration_seconds"] = 4
		script["scenes"][0]["action"] = "[0-1s] Grip the product.\n[1-4s] Move it along the table."
		script["scenes"][1:1] = [second, middle]
		with self.assertRaisesRegex(ValueError, "Scene 3 has no completed"):
			validate_script(script, self.inventory, self.constraints)

	def test_stationary_product_detail_is_not_rejected_by_motion_label_alone(self):
		script = sample_script()
		script["scenes"][0]["subject_motion"] = "stationary"
		script["scenes"][-1]["subject_motion"] = "stationary"
		self.assertEqual(script, validate_script(script, self.inventory, self.constraints))

	def test_opening_rule_cannot_preacquire_its_action_target(self):
		script = sample_script()
		script["scenes"][0]["continuity_rules"] = (
			"The mascot starts beside the table, holding the tissue pack."
		)
		script["scenes"][0]["action"] = "[0-6s] The mascot reaches for the tissue pack and grasps it."
		with self.assertRaisesRegex(ValueError, "holding tissue pack"):
			validate_script(script, self.inventory, self.constraints)

	def test_camera_opening_cannot_preacquire_the_same_product_with_brand_modifier(self):
		script = sample_script()
		script["scenes"][0]["visual_camera"] = (
			"The actor is seated beside the table, holding a Shera tissue pack."
		)
		script["scenes"][0]["action"] = "[0-6s] The actor reaches for the tissue pack and grasps it."
		with self.assertRaisesRegex(ValueError, "opens holding Shera tissue pack"):
			validate_script(script, self.inventory, self.constraints)

	def test_camera_only_phase_cannot_replace_product_action(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The camera pans over the product."
		with self.assertRaisesRegex(ValueError, "Move camera movement out of Action"):
			validate_script(script, self.inventory, self.constraints)

	def test_camera_sentence_is_removed_when_a_real_timed_action_remains(self):
		script = sample_script()
		script["scenes"][0]["action"] = (
			"[0-1s] The camera pushes in. Grip the product.\n[1-6s] Move it along the table."
		)
		validated = validate_script(script, self.inventory, self.constraints)
		self.assertEqual(
			"[0-1s] Grip the product.\n[1-6s] Move it along the table.",
			validated["scenes"][0]["action"],
		)

	def test_dab_is_a_completed_contact_action(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The mascot dabs its cheek with the supplied tissue."
		self.assertEqual(script, validate_script(script, self.inventory, self.constraints))

	def test_unanchored_fluid_effect_requires_action_reference(self):
		script = sample_script()
		script["scenes"][0]["action"] = (
			"[0-2s] Juice spills on the table.\n[2-6s] The product absorbs the liquid spill."
		)
		with self.assertRaisesRegex(ValueError, "supplied action reference"):
			validate_script(script, self.inventory, {**self.constraints, "action_reference_observations": []})
		self.assertEqual(
			script,
			validate_script(
				script,
				self.inventory,
				{**self.constraints, "action_reference_observations": ["observed spill contact"]},
			),
		)
		# The writer already permits a physical effect explicitly requested in
		# creative direction; validation must use that same authorization source.
		self.assertEqual(
			script,
			validate_script(
				script,
				self.inventory,
				{
					**self.constraints,
					"action_reference_observations": [],
					"creative_direction": "Show Shera tissue absorption of a small spill",
				},
			),
		)

	def test_unanchored_cleaning_and_anonymous_actor_are_rejected(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The product wipes dust from a shelf."
		with self.assertRaisesRegex(ValueError, "cleaning, fluid"):
			validate_script(script, self.inventory, {**self.constraints, "action_reference_observations": []})
		script["scenes"][0]["action"] = "[0-6s] An off-screen hand places the product on the table."
		with self.assertRaisesRegex(ValueError, "anonymous human"):
			validate_script(script, self.inventory, self.constraints)

	def test_automatic_review_cannot_defer_unsupported_water_action(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The mascot wipes water from the table with the tissue."
		with self.assertRaisesRegex(ValueError, "supplied action reference"):
			validate_script(
				script,
				self.inventory,
				{**self.constraints, "action_reference_observations": []},
				[],
			)

	def test_wet_surface_requires_an_earlier_visible_cause(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The mascot wipes a wet surface with the tissue."
		with self.assertRaisesRegex(ValueError, "never became wet on camera"):
			validate_script(
				script,
				self.inventory,
				{**self.constraints, "action_reference_observations": ["observed water contact"]},
				[],
			)

	def test_dropping_a_dry_prop_does_not_establish_a_water_spill(self):
		script = sample_script()
		script["scenes"][0]["action"] = (
			"[0-3s] The mascot drops a cookie.\n[3-6s] The mascot wipes a wet surface with the tissue."
		)
		with self.assertRaisesRegex(ValueError, "never became wet on camera"):
			validate_script(
				script,
				self.inventory,
				{**self.constraints, "action_reference_observations": ["observed water contact"]},
				[],
			)

	def test_visible_water_droplets_falling_count_as_a_wet_cause(self):
		from joymedia.services.planning.creative import WET_EVENT

		self.assertIsNotNone(WET_EVENT.search("Water droplets fall onto the tissue."))
		self.assertIsNone(WET_EVENT.search("The mascot drops a dry cookie."))

	def test_saying_a_spill_remains_does_not_show_its_cause(self):
		script = sample_script()
		script["scenes"][0]["action"] = (
			"[0-3s] A spill remains visible.\n[3-6s] The mascot wipes a wet surface with the tissue."
		)
		with self.assertRaisesRegex(ValueError, "never happened on camera"):
			validate_script(
				script,
				self.inventory,
				{**self.constraints, "action_reference_observations": ["observed water contact"]},
				[],
			)

	def test_discard_requires_a_visible_supported_destination(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The mascot discards the used tissue away from the pack."
		with self.assertRaisesRegex(ValueError, "without a visible destination"):
			validate_script(script, self.inventory, self.constraints, [])

	def test_schema_descriptions_reach_model_context_as_well_as_the_decoder(self):
		from joymedia.services.planning.production import _request_planner

		schema = {
			"type": "object",
			"properties": {"value": {"type": "string", "description": "A semantic field instruction."}},
			"required": ["value"],
			"additionalProperties": False,
		}
		response = _streamed('{"value":"done"}')
		with (
			patch(
				"joymedia.services.runtime.endpoints.endpoint",
				return_value=frappe._dict(base_url="http://planner/v1", model="configured", timeout=30),
			),
			patch("joymedia.services.planning.plan_parsing._completion_budget", return_value=100),
			patch("joymedia.services.runtime.streaming.requests.post", return_value=response) as post,
		):
			_request_planner("Write the object.", system="JSON only.", max_tokens=100, response_schema=schema)
		payload = post.call_args.kwargs["json"]
		self.assertIn("A semantic field instruction.", payload["messages"][0]["content"])
		self.assertEqual(schema, payload["response_format"]["json_schema"]["schema"])

	def test_unreachable_planner_is_reported_as_service_outage(self):
		import requests

		from joymedia.services.planning.production import PlannerUnavailableError, _request_planner

		with (
			patch(
				"joymedia.services.runtime.endpoints.endpoint",
				return_value=frappe._dict(base_url="http://planner/v1", model="configured", timeout=30),
			),
			patch(
				"joymedia.services.runtime.streaming.requests.post",
				side_effect=requests.ConnectionError("offline"),
			),
		):
			with self.assertRaises(PlannerUnavailableError):
				_request_planner("Write the object.", system="JSON only.", max_tokens=100)

	def test_a_lost_planner_answer_is_detected_while_streaming_and_asked_once_more(self):
		import requests

		from joymedia.services.planning.production import PLANNER_IDLE_SECONDS, _request_planner

		calls = []

		def reply(*args, **kwargs):
			calls.append(kwargs)
			if len(calls) == 1:
				raise requests.ConnectionError("Read timed out.")
			return _streamed('{"value":"done"}')

		with (
			patch(
				"joymedia.services.runtime.endpoints.endpoint",
				return_value=frappe._dict(base_url="http://planner/v1", model="configured", timeout=600),
			),
			patch("joymedia.services.planning.plan_parsing._completion_budget", return_value=100),
			patch("joymedia.services.runtime.streaming.requests.post", side_effect=reply),
		):
			self.assertEqual(
				{"value": "done"}, _request_planner("Write the object.", system="JSON only.", max_tokens=100)
			)
		# Idle, not the whole 600 s answer budget, decides that an answer was lost.
		self.assertEqual((10, PLANNER_IDLE_SECONDS), calls[0]["timeout"])
		self.assertTrue(calls[0]["json"]["stream"])
		# Same request both times: the seed makes the retried answer identical.
		self.assertEqual(calls[0]["json"]["seed"], calls[1]["json"]["seed"])

	def test_malformed_planner_json_gets_one_new_seed(self):
		from joymedia.services.planning.production import _request_planner

		bad = _streamed("no json")
		good = _streamed('{"value":"done"}')
		seeds = []

		def reply(*args, **kwargs):
			seeds.append(kwargs["json"]["seed"])
			return [bad, good][len(seeds) - 1]

		with (
			patch(
				"joymedia.services.runtime.endpoints.endpoint",
				return_value=frappe._dict(base_url="http://planner/v1", model="configured", timeout=30),
			),
			patch("joymedia.services.planning.plan_parsing._completion_budget", return_value=100),
			patch("joymedia.services.runtime.streaming.requests.post", side_effect=reply),
		):
			self.assertEqual(
				{"value": "done"}, _request_planner("Write the object.", system="JSON only.", max_tokens=100)
			)
		self.assertEqual(2, len(seeds))
		self.assertNotEqual(*seeds)

	def test_frame_review_resume_requires_current_native_approval_without_erasing_findings(self):
		from joymedia.services.generation.creative_batch import _keyframe_ready

		shot = frappe._dict(name="shot", consistency_status="Needs Review", keyframe_status="Pending Review")
		self.assertFalse(_keyframe_ready(shot))
		shot.keyframe_status = "Approved"
		with (
			patch("frappe.get_doc", return_value=shot),
			patch("joymedia.services.keyframes.stage.approved_keyframe_task", return_value=None) as approved,
		):
			self.assertFalse(_keyframe_ready(shot))
			approved.return_value = "current-keyframe-task"
			self.assertTrue(_keyframe_ready(shot))
		self.assertEqual("Needs Review", shot.consistency_status)

	def test_omission_retraction_requires_existing_action_text_and_never_qualifies_pixels(self):
		from joymedia.services.planning.script_review import _cross_check_missing_actions

		issue = {
			"scene": 1,
			"category": "missing_contact_or_result",
			"quote": "Grip the product.",
			"instruction": "Show movement.",
		}
		for quote in ("", "Move it along the table.", "Invented result not in the script"):
			with (
				self.subTest(quote=quote),
				patch(
					"joymedia.services.planning.production._ask_planner",
					return_value={"already_written": quote},
				),
			):
				review = {"issues": [copy.deepcopy(issue)]}
				if quote == "Invented result not in the script":
					finding = _cross_check_missing_actions(review, sample_script())["issues"][0]
					self.assertEqual(issue["category"], finding["category"])
					self.assertIn("absent", finding["cross_check_error"])
					self.assertNotIn("text_cross_check", finding)
				else:
					finding = _cross_check_missing_actions(review, sample_script())["issues"][0]
					self.assertEqual(
						"production_detail" if quote else "missing_contact_or_result", finding["category"]
					)
					if quote:
						self.assertFalse(finding["text_cross_check"]["physical_qualification"])

	def test_staged_opening_can_establish_reach_before_first_action(self):
		from joymedia.services.planning.script_review import _cross_check_missing_actions

		script = sample_script()
		script["scenes"][0]["visual_camera"] = (
			"The actor is beside the table, with the product within easy reach."
		)
		issue = {
			"scene": 1,
			"category": "missing_prerequisite",
			"quote": "Grip the product.",
			"instruction": "Place the actor within easy reach before gripping.",
		}
		with patch(
			"joymedia.services.planning.production._ask_planner",
			return_value={"already_written": "the product within easy reach"},
		):
			finding = _cross_check_missing_actions({"issues": [issue]}, script)["issues"][0]
		self.assertEqual("production_detail", finding["category"])
		self.assertFalse(finding["text_cross_check"]["physical_qualification"])

	def test_idle_retraction_requires_progress_in_the_same_scene(self):
		from joymedia.services.planning.script_review import _cross_check_missing_actions

		for quote, accepted in [
			("Move it along the table.", True),
			("Turn the product to face forward.", False),
			("", True),
		]:
			with (
				self.subTest(quote=quote),
				patch(
					"joymedia.services.planning.production._ask_planner",
					return_value={"already_written": quote},
				),
			):
				review = {
					"issues": [
						{
							"scene": 1,
							"category": "idle_pacing",
							"quote": "Grip the product.",
							"instruction": "Add movement.",
						}
					]
				}
				if accepted:
					finding = _cross_check_missing_actions(review, sample_script())["issues"][0]
					self.assertEqual("production_detail" if quote else "idle_pacing", finding["category"])
				else:
					finding = _cross_check_missing_actions(review, sample_script())["issues"][0]
					self.assertEqual("idle_pacing", finding["category"])
					self.assertIn("absent", finding["cross_check_error"])
					self.assertNotIn("text_cross_check", finding)

	def test_retry_rejected_script_changes_cache_identity_but_keeps_accepted_work(self):
		from joymedia.api.creative import retry_product_variant

		for script in (None, {"title": "Accepted story"}):
			variant = {
				"status": "Needs Attention",
				"resume_stage": "Planning",
				"nonce": "old",
				"error": "Rejected draft",
			}
			if script:
				variant["script"] = script
				variant["pose_prepared"] = True
				variant["pose_views"] = [{"scene": 1, "status": "deferred"}]
			batch = Mock(name="batch", status="Needs Attention", variants_json=json.dumps([variant]))
			batch.name = "BATCH"
			with (
				self.subTest(script=script),
				patch("frappe.get_doc", return_value=batch),
				patch.object(frappe.cache, "lock"),
				patch.object(frappe.db, "commit"),
				patch.object(frappe.db, "set_value") as save,
				patch("frappe.enqueue") as enqueue,
				patch(
					"joymedia.services.generation.creative_batch._planning_queue",
					return_value="joymedia_planning",
				),
			):
				retry_product_variant(batch.name, 1)
				self.assertEqual("joymedia_planning", enqueue.call_args.kwargs["queue"])
				self.assertEqual(10800, enqueue.call_args.kwargs["timeout"])
				retried = json.loads(save.call_args.args[2]["variants_json"])[0]
				if script:
					self.assertEqual("old", retried["nonce"])
					self.assertEqual(script, retried["script"])
					self.assertFalse(retried["pose_prepared"])
					self.assertEqual("deferred", retried["pose_views"][0]["status"])
				else:
					self.assertNotEqual("old", retried["nonce"])
					self.assertEqual(
						[{"nonce": "old", "error": "Rejected draft"}], retried["script_attempts"]
					)

	def test_retry_after_a_pose_stop_resolves_those_scenes_instead_of_drawing_old_bindings(self):
		from joymedia.api.creative import retry_product_variant

		variant = {
			"status": "Needs Attention",
			"resume_stage": "Keyframes",
			"project": "PRJ-1",
			"script": {"scenes": [{"cast": ["bear"]}, {"cast": ["bear"]}, {"cast": []}]},
			"pose_views": [{"scene": 1, "status": "deferred"}, {"scene": 2, "status": "ready"}],
		}
		batch = Mock(name="batch", status="Needs Attention", variants_json=json.dumps([variant]))
		batch.name = "BATCH"
		with (
			patch("frappe.get_doc", return_value=batch),
			patch("frappe.get_all", return_value=[]),
			patch.object(frappe.cache, "lock"),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "set_value") as save,
			patch("frappe.enqueue") as enqueue,
			patch(
				"joymedia.services.generation.creative_batch._planning_queue",
				return_value="joymedia_planning",
			),
		):
			result = retry_product_variant(batch.name, 1)
		self.assertEqual("Rewriting", result["status"])
		self.assertIn("rewrite_scenes_in_place", enqueue.call_args.args[0])
		retried = json.loads(save.call_args.args[2]["variants_json"])[0]
		self.assertEqual({"pose_scenes": [1], "by": "Retry"}, retried["scene_revision"])

	def test_final_automatic_script_retry_uses_advisory_fallback_once(self):
		from joymedia.services.generation.creative_batch import (
			AUTOMATIC_SCRIPT_REDRAWS,
			_redraw_invalid_automatic_script,
		)

		variant = {
			"status": "Planning",
			"nonce": "last-clean-attempt",
			"automatic_script_redraws": AUTOMATIC_SCRIPT_REDRAWS,
		}
		error = ValueError("Automatic screenplay quality retries exhausted: two advisory notes conflict.")
		self.assertTrue(_redraw_invalid_automatic_script(variant, error))
		self.assertTrue(variant["accept_advisory_fallback"])
		self.assertEqual("Queued", variant["status"])
		self.assertFalse(_redraw_invalid_automatic_script(variant, error))

	def test_gallery_views_do_not_choose_the_script_product_identity(self):
		inventory = [
			{
				"key": "front",
				"role": "Product",
				"identity": "one_product",
				"views": [{"key": "front"}, {"key": "back"}],
			}
		]
		script = sample_script()
		for scene in script["scenes"]:
			scene["products"] = ["front"]
		self.assertEqual(
			["front"], validate_script(script, inventory, self.constraints)["scenes"][0]["products"]
		)
		script["scenes"][0]["products"] = ["back"]
		with self.assertRaisesRegex(ValueError, "supplied identities only"):
			validate_script(script, inventory, self.constraints)
		script["scenes"][0]["products"] = ["front", "back"]
		with self.assertRaisesRegex(ValueError, "supplied identities only"):
			validate_script(script, inventory, self.constraints)

	def test_generated_timing_reuses_frame_allocation_without_dropping_or_inventing_actions(self):
		from joymedia.services.planning.creative import fit_generated_timing
		from joymedia.services.planning.durations import allocate_frames
		from joymedia.services.planning.timed_actions import read_timed_actions

		script = sample_script()
		script["scenes"][0].update(
			duration_seconds=3, action="[0-0.5s] Grip the product. [0.5-3s] Move it along the table."
		)
		script["scenes"][1].update(duration_seconds=2, action="[0-1s] Turn it. [1-2s] Hold it.")
		compiled = fit_generated_timing(script, 10, 24)
		self.assertEqual([6, 4], [s["duration_seconds"] for s in compiled["scenes"]])
		self.assertEqual(240, sum(compiled["timing_compilation"]["scene_frames"]))
		self.assertEqual(
			["Grip the product.", "Move it along the table."],
			[p["action"] for p in read_timed_actions(compiled["scenes"][0]["action"], 6)],
		)
		self.assertEqual([22, 1, 1], allocate_frames([1000, 0.001, 0.001], 24))
		self.assertEqual(2, len(compiled["scenes"]))

	def test_planner_cache_does_not_reuse_another_configured_models_answer(self):
		from joymedia.services.planning.production import _ask_planner

		with (
			patch(
				"joymedia.services.runtime.endpoints.endpoint",
				side_effect=[
					frappe._dict(model="first", base_url="http://planner/v1"),
					frappe._dict(model="second", base_url="http://planner/v1"),
				],
			),
			patch(
				"joymedia.services.planning.production._request_planner",
				side_effect=[{"from": "first"}, {"from": "second"}],
			) as planner,
			patch("frappe.cache.get_value", return_value=None) as cache_read,
			patch("frappe.cache.set_value"),
		):
			self.assertEqual({"from": "first"}, _ask_planner("same script request"))
			self.assertEqual({"from": "second"}, _ask_planner("same script request"))
		self.assertEqual(2, planner.call_count)
		self.assertNotEqual(cache_read.call_args_list[0].args[0], cache_read.call_args_list[1].args[0])

	def test_second_pass_rejects_missing_scene_evidence(self):
		from joymedia.services.planning.creative import review_script_actions

		with patch(
			"joymedia.services.planning.production._ask_planner", return_value={"findings": []}
		) as planner:
			with self.assertRaisesRegex(ValueError, "each scene"):
				review_script_actions(
					sample_script(),
					[{"key": "mascot-reference", "role": "Character"}],
					[
						{"text": "Maintain real contact", "source": "owner-note", "scope": "Current"},
						{"text": "Earlier rendered failure", "source": "old-note", "scope": "Historical"},
					],
				)
		self.assertIn("mascot-reference", planner.call_args.args[0])
		self.assertIn("Maintain real contact", planner.call_args.args[0])
		self.assertNotIn("Earlier rendered failure", planner.call_args.args[0])

	def test_script_review_accepts_grounded_coverage_and_rejects_invented_issue_evidence(self):
		from joymedia.services.planning.creative import review_script_actions

		good = {
			"coverage": [
				{"scene": 1, "action_quote": "Grip the product."},
				{"scene": 2, "action_quote": "Turn the product to face forward."},
			],
			"issues": [],
		}
		with patch("joymedia.services.planning.production._ask_planner", return_value=good):
			self.assertEqual(good, review_script_actions(sample_script()))
		bad = copy.deepcopy(good)
		bad["issues"] = [
			{
				"scene": 1,
				"category": "unreferenced_actor",
				"quote": "An unreferenced presenter appears.",
				"instruction": "Remove the presenter.",
			}
		]
		with patch("joymedia.services.planning.production._ask_planner", return_value=bad):
			with self.assertRaisesRegex(ValueError, "grounded"):
				review_script_actions(sample_script())

	def test_static_closing_packshot_is_not_misclassified_as_idle(self):
		from joymedia.services.planning.script_review import _filter_allowed_product_presentation

		script = sample_script()
		issues = [
			{"scene": 1, "category": "idle_pacing", "quote": "Grip the product."},
			{"scene": 2, "category": "idle_pacing", "quote": "Turn the product to face forward."},
		]
		result = _filter_allowed_product_presentation({"issues": issues}, script)
		self.assertEqual([issues[0]], result["issues"])
		script["scenes"][-1]["cast"] = ["mascot"]
		result = _filter_allowed_product_presentation({"issues": copy.deepcopy(issues)}, script)
		self.assertEqual(2, len(result["issues"]))

	def test_inactive_actor_is_removed_from_static_final_packshot(self):
		from joymedia.services.planning.creative import normalize_static_final_packshot

		script = sample_script()
		last = script["scenes"][-1]
		last.update(
			cast=["mascot"],
			action="[0-4s] The mascot stands beside the product.",
			continuity_rules="The mascot remains beside the product.",
		)
		self.assertTrue(normalize_static_final_packshot(script))
		self.assertEqual([], last["cast"])
		self.assertNotIn("mascot", last["action"] + last["visual_camera"] + last["continuity_rules"])
		self.assertIn("established physical support", last["continuity_rules"])
		last.update(cast=["mascot"], action="[0-4s] The mascot turns the product to camera.")
		self.assertEqual([], normalize_static_final_packshot(script))

	def test_action_sources_share_bounded_context_in_chronological_order(self):
		from joymedia.services.intake.action_reference import action_observations

		versions = [
			frappe._dict(
				name=name,
				analysis_json=json.dumps(
					{
						"action_reference": {
							"clips": [{"start": i, "end": i + 1, "caption": f"{name}-{i}"} for i in range(6)]
						}
					}
				),
			)
			for name in ("camera", "action")
		]
		with patch("joymedia.services.intake.cinematography.motion_references", return_value=versions):
			observations = action_observations(None)[:8]
		self.assertEqual(["camera", "action"] * 4, [r["source"] for r in observations])
		self.assertEqual([0, 0, 1, 1, 2, 2, 3, 3], [r["start"] for r in observations])

	def test_script_repair_preserves_all_prior_errors_and_uses_script_system(self):
		from joymedia.services.planning.creative import draft_script

		bad_count = sample_script()
		bad_count["scenes"] = bad_count["scenes"][:1]
		bad_enum = sample_script()
		bad_enum["scenes"][0]["shot_framing"] = "Medium"
		project = frappe._dict(
			total_duration_seconds=10,
			delivery_width=1280,
			delivery_height=720,
			video_idea="Keep the foreground clear.",
		)
		inventory = [
			{
				"key": "product",
				"role": "Product",
				"identity": "internal-id",
				"label": "Label",
				"keep_rule": "Keep the original connected proportions.",
				"views": [
					{
						"description": "Stale pose caption on a pedestal.",
						"identity_description": "Blue package with its original printed artwork.",
					}
				],
			}
		]
		with (
			patch("joymedia.services.planning.creative.reference_inventory", return_value=inventory),
			patch("joymedia.services.intake.action_reference.action_observations", return_value=[]),
			patch("joymedia.services.intake.references.brand", return_value={}),
			patch(
				"joymedia.services.planning.creative.review_script_actions",
				return_value={"coverage": [], "issues": []},
			),
			patch(
				"joymedia.services.planning.production._ask_planner",
				side_effect=[bad_count, bad_enum, sample_script()],
			) as planner,
		):
			expected = sample_script()
			expected["action_review"] = {"coverage": [], "issues": []}
			expected["director_notes"] = []
			expected["writer_attempts"] = 3
			from joymedia.services.planning.creative import direct_camera

			expected["camera_adjustments"] = direct_camera(expected["scenes"])
			expected["wording_adjustments"] = []
			actual = draft_script(
				project,
				nonce="varied",
				review_notes=[{"source": "old-note", "text": "Prior version observation."}],
			)
			actual.pop("timing_compilation")
			self.assertEqual(expected, actual)
		last = planner.call_args
		self.assertIn("2–12 scenes", last.args[0])
		self.assertIn("Unsupported shot_framing", last.args[0])
		self.assertNotIn('"identity": "internal-id"', last.args[0])
		self.assertIn("Blue package with its original printed artwork.", last.args[0])
		self.assertNotIn("Stale pose caption on a pedestal.", last.args[0])
		self.assertIn("Keep the original connected proportions.", last.args[0])
		self.assertNotIn("Prior version observation.", last.args[0])
		self.assertIn("PRIMARY USER DIRECTION:", last.kwargs["system"])
		self.assertIn("canonical character identities", last.kwargs["system"])
		self.assertNotIn("concrete supplied view key", last.kwargs["system"])
		self.assertIn("multi-scene", last.kwargs["system"])
		self.assertEqual("writer", last.kwargs["capability"])
		self.assertIn("scenes", last.kwargs["response_schema"]["properties"])

	def test_director_reference_choices_hide_alternate_pose_views(self):
		from joymedia.services.planning.creative import reference_choices, script_schema

		inventory = [
			{
				"key": "mascot",
				"role": "Character",
				"identity": "shera",
				"views": [
					{"key": "mascot", "description": "Original identity photograph."},
					{"key": "pose_standing", "description": "Qualified standing pose."},
					{"key": "pose_side", "description": "Qualified side pose."},
				],
			},
			{"key": "product", "role": "Product", "identity": "shera_pack", "views": [{"key": "product"}]},
		]
		self.assertEqual(
			{
				"mascot": {"role": "Character", "identity": "shera"},
				"product": {"role": "Product", "identity": "shera_pack"},
			},
			reference_choices(inventory),
		)
		schema = script_schema(inventory, {"duration_seconds": None, "fps": 24, "max_scene_frames": None})
		cast = schema["properties"]["scenes"]["items"]["properties"]["cast"]["items"]["enum"]
		self.assertEqual(["mascot"], cast)

	def test_production_detail_reaches_planning_and_unresolved_finding_reaches_reviewer(self):
		from joymedia.services.planning.creative import draft_script

		project = frappe._dict(total_duration_seconds=10, delivery_width=1280, delivery_height=720)
		inventory = [
			{
				"key": "product",
				"role": "Product",
				"identity": "product",
				"label": "Product",
				"views": [{"description": "Blue product"}],
			}
		]
		instruction = "Maintain supported contact throughout the movement."
		for category in ("production_detail", "missing_prerequisite"):
			with (
				patch("joymedia.services.planning.creative.reference_inventory", return_value=inventory),
				patch("joymedia.services.intake.action_reference.action_observations", return_value=[]),
				patch("joymedia.services.intake.references.brand", return_value={}),
				patch(
					"joymedia.services.planning.production._ask_planner",
					side_effect=lambda *a, **k: copy.deepcopy(sample_script()),
				) as writer,
				patch(
					"joymedia.services.planning.creative.review_script_actions",
					return_value={
						"coverage": [],
						"issues": [
							{
								"scene": 1,
								"category": category,
								"quote": "Move it along the table.",
								"instruction": instruction,
							}
						],
					},
				),
			):
				if category == "production_detail":
					self.assertIn(
						instruction,
						draft_script(project, nonce="production-note")["scenes"][0]["continuity_rules"],
					)
				else:
					# Two rewrites, then the reviewer decides; the draft is not discarded.
					script = draft_script(project, nonce="blocking-note")
					self.assertEqual(["Scene 1: " + instruction], script["director_notes"])
					self.assertNotIn(instruction, script["scenes"][0]["continuity_rules"])
					self.assertEqual(3, writer.call_count)
					self.assertIn(
						"INVARIANTS FOR ORIGINAL WRITING AND EVERY REPAIR", writer.call_args.kwargs["system"]
					)
					self.assertIn("unused stock", writer.call_args.kwargs["system"])
					self.assertIn("LATEST SCREENPLAY:", writer.call_args.args[0])
					self.assertIn(sample_script()["scenes"][0]["visual_camera"], writer.call_args.args[0])
					self.assertEqual("creative_script_repair", writer.call_args.kwargs["sampling_profile"])

	def test_automatic_writer_continues_with_review_notes_after_bounded_repair(self):
		from joymedia.services.planning.creative import draft_script

		project = frappe._dict(total_duration_seconds=10, delivery_width=1280, delivery_height=720)
		inventory = [
			{
				"key": "product",
				"role": "Product",
				"identity": "product",
				"label": "Product",
				"views": [{"description": "Blue product"}],
			}
		]
		issue = {
			"scene": 1,
			"category": "missing_prerequisite",
			"quote": "Move it along the table.",
			"instruction": "Acquire the item before use.",
		}
		with (
			patch("joymedia.services.planning.creative.reference_inventory", return_value=inventory),
			patch("joymedia.services.intake.action_reference.action_observations", return_value=[]),
			patch("joymedia.services.intake.references.brand", return_value={}),
			patch(
				"joymedia.services.planning.production._ask_planner",
				side_effect=lambda *a, **k: copy.deepcopy(sample_script()),
			) as writer,
			patch(
				"joymedia.services.planning.creative.review_script_actions",
				return_value={"coverage": [], "issues": [issue]},
			),
			patch("joymedia.services.planning.creative._save_rejected_drafts") as evidence,
		):
			script = draft_script(project, nonce="strict", require_clean=True)
		self.assertEqual(6, writer.call_count)
		evidence.assert_called_once()
		self.assertEqual(["Scene 1: Acquire the item before use."], script["director_notes"])
		self.assertEqual("deferred", script["writer_fallback"]["quality_review"])

	def test_reviewer_protocol_failure_does_not_reject_a_structurally_valid_automatic_script(self):
		from joymedia.services.planning.creative import draft_script

		project = frappe._dict(total_duration_seconds=10, delivery_width=1280, delivery_height=720)
		inventory = [
			{
				"key": "product",
				"role": "Product",
				"identity": "product",
				"label": "Product",
				"views": [{"description": "Blue product"}],
			}
		]
		with (
			patch("joymedia.services.planning.creative.reference_inventory", return_value=inventory),
			patch("joymedia.services.intake.action_reference.action_observations", return_value=[]),
			patch("joymedia.services.intake.references.brand", return_value={}),
			patch("joymedia.services.planning.production._ask_planner", return_value=sample_script()),
			patch(
				"joymedia.services.planning.creative.review_script_actions",
				side_effect=ValueError("bad quote"),
			),
			patch("frappe.logger") as logger,
		):
			script = draft_script(project, nonce="review-outage", require_clean=True)
		self.assertEqual("bad quote", script["review_unavailable"])
		self.assertEqual([], script["director_notes"])
		logger.return_value.warning.assert_called_once()

	def test_invalid_writer_json_retries_before_stopping_automatic_batch(self):
		from joymedia.services.planning.creative import draft_script

		project = frappe._dict(total_duration_seconds=10, delivery_width=1280, delivery_height=720)
		inventory = [
			{
				"key": "product",
				"role": "Product",
				"identity": "product",
				"label": "Product",
				"views": [{"description": "Blue product"}],
			}
		]
		with (
			patch("joymedia.services.planning.creative.reference_inventory", return_value=inventory),
			patch("joymedia.services.intake.action_reference.action_observations", return_value=[]),
			patch("joymedia.services.intake.references.brand", return_value={}),
			patch(
				"joymedia.services.planning.production._ask_planner",
				side_effect=[ValueError("No valid JSON object"), sample_script()],
			) as writer,
			patch(
				"joymedia.services.planning.creative.review_script_actions",
				return_value={"coverage": [], "issues": []},
			),
		):
			script = draft_script(project, nonce="retry-json", require_clean=True)
		self.assertEqual(2, writer.call_count)
		self.assertEqual("A moving product", script["title"])

	def test_authored_geometry_timing_and_cast_remain_authoritative(self):
		self.assertEqual(sample_script(), validate_script(sample_script(), self.inventory, self.constraints))
		for mutate in (
			lambda s: s.update(format="9:16"),
			lambda s: s.update(duration_seconds=30),
			lambda s: s.update(duration_seconds=float("nan")),
			lambda s: s["scenes"][0].update(cast=["invented_actor"]),
			lambda s: s["scenes"][0].update(action="The camera moves slowly."),
			lambda s: s["scenes"][0].update(action="[0-1s] Grip.\n[2-6s] Move."),
			lambda s: s["scenes"][0].update(duration_seconds=float("nan")),
		):
			script = sample_script()
			mutate(script)
			with self.subTest(script=script), self.assertRaises(ValueError):
				validate_script(script, self.inventory, self.constraints)

	def test_selected_seated_reference_can_plan_a_supported_pose_bridge(self):
		inventory = [
			*self.inventory,
			{
				"key": "bear",
				"role": "Character",
				"identity": "bear",
				"views": [
					{
						"key": "bear",
						"pose_and_support": "Seated on a flat ground plane; no walking pose visible.",
					}
				],
			},
		]
		script = sample_script()
		script["scenes"][0]["cast"] = ["bear"]
		script["scenes"][0]["action"] = (
			"[0-1s] The bear stands up.\n[1-6s] The bear walks toward the product."
		)
		self.assertEqual(script, validate_script(script, inventory, self.constraints, []))

	def test_optional_rewrite_failure_preserves_a_valid_draft_and_pose_choices(self):
		from joymedia.services.planning.creative import draft_script

		project = frappe._dict(total_duration_seconds=10, delivery_width=1280, delivery_height=720)
		inventory = [
			{
				"key": "product",
				"role": "Product",
				"identity": "same",
				"label": "Product",
				"views": [
					{"key": "product", "description": "Front view"},
					{"key": "product_side", "description": "Side view of the same product"},
				],
			}
		]
		invalid = sample_script()
		invalid["scenes"][0]["shot_framing"] = "invalid"
		issue = {
			"scene": 1,
			"category": "idle_pacing",
			"quote": "Move it along the table.",
			"instruction": "Make the interaction brisker.",
		}
		with (
			patch("joymedia.services.planning.creative.reference_inventory", return_value=inventory),
			patch("joymedia.services.intake.action_reference.action_observations", return_value=[]),
			patch("joymedia.services.intake.references.brand", return_value={}),
			patch(
				"joymedia.services.planning.production._ask_planner",
				side_effect=[sample_script(), *[copy.deepcopy(invalid) for _ in range(5)]],
			) as writer,
			patch(
				"joymedia.services.planning.creative.review_script_actions",
				return_value={"coverage": [], "issues": [issue]},
			),
			patch("joymedia.services.planning.creative._save_rejected_drafts") as evidence,
		):
			result = draft_script(
				project, nonce="retained-draft", examples={"claims": ["Unrelated strength guarantee"]}
			)
		self.assertEqual("medium", result["scenes"][0]["shot_framing"])
		self.assertEqual(["Scene 1: Make the interaction brisker."], result["director_notes"])
		self.assertEqual("deferred", result["writer_fallback"]["quality_review"])
		self.assertNotIn("Unrelated strength guarantee", writer.call_args.args[0])
		choices = writer.call_args.kwargs["response_schema"]["properties"]["scenes"]["items"]["properties"][
			"products"
		]["items"]["enum"]
		self.assertEqual(["product"], choices)
		evidence.assert_called_once()

	def test_physical_props_require_exact_authored_evidence_and_cannot_replace_actors(self):
		base = {
			"version": 1,
			"entities": [{"id": "actor", "label": "the supplied actor"}],
			"relations": [],
			"checks": [],
			"events": [{"id": "action1", "description": "Move", "start": 0, "end": 1, "after": []}],
		}
		inferred = {
			"additional_entities": [{"id": "support", "source_quote": "wooden table", "kind": "support"}],
			"relations": [{"kind": "supported_by", "subject": "actor", "object": "support"}],
			"events": [{"id": "invented"}],
		}
		result = grounded_contract(base, inferred, "The actor acts on a wooden table.")
		self.assertEqual(base["events"], result["events"])
		self.assertEqual("wooden table", result["entities"][-1]["label"])
		for field, value in (("source_quote", "chair"), ("kind", "actor"), ("id", "actor")):
			bad = copy.deepcopy(inferred)
			bad["additional_entities"][0][field] = value
			with self.subTest(field=field), self.assertRaises(ValueError):
				grounded_contract(base, bad, "The actor acts on a wooden table.")

	def test_inferred_reveal_uses_available_tracking_without_changing_explicit_controls(self):
		from joymedia.services.planning.camera import (
			camera_plan,
			executable_inferred_intent,
			infer_cinematic_intent,
		)

		structure = {
			"stage": "establish",
			"framing": "wide",
			"angle": "eye_level",
			"subject_motion": "locomotion",
			"keep_visible": [],
		}
		preferred = {"behavior": "arc", "allow_reframe": True, "purpose": "hook", "energy": "brisk"}
		resolved = executable_inferred_intent(preferred, structure, set())
		self.assertEqual("tracking", resolved["behavior"])
		self.assertEqual("arc", preferred["behavior"])
		# A coarse extraction label must not lock a genuinely travelling subject
		# out of frame; explicit camera_motion=locked remains authoritative below.
		self.assertEqual("tracking", infer_cinematic_intent(dict(structure, stage="extract"))["behavior"])
		shot = {
			"shot_number": 1,
			"motion_plan_json": {"shot_structure": structure, "camera_intent": resolved},
		}
		self.assertEqual("tracking", camera_plan(shot, {})["behavior"])
		shot["motion_plan_json"]["camera_motion"] = "locked"
		self.assertEqual("locked", camera_plan(shot, {})["behavior"])

	def test_actual_frozen_keyframe_supplies_framing_evidence_without_manual_upload(self):
		from types import SimpleNamespace

		from PIL import Image

		from joymedia.services.planning.framing import inspect_framing

		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "keyframe.png"
			Image.new("RGB", (200, 400), "white").save(path)
			artifact = SimpleNamespace(name="frozen-artifact", frappe_file="/private/files/keyframe.png")
			with (
				patch(
					"frappe.get_doc",
					side_effect=lambda kind, *args: artifact
					if kind == "Generation Artifact"
					else SimpleNamespace(get_full_path=lambda: str(path)),
				),
				patch(
					"frappe.get_site_path",
					side_effect=lambda *args: str(Path(directory) / "cache" / args[-1]),
				),
				patch("joymedia.services.runtime.endpoints.is_configured", return_value=True),
				patch(
					"joymedia.services.runtime.endpoints.endpoint", return_value=frappe._dict(model="vision")
				),
				patch(
					"joymedia.services.review.consistency.ask",
					return_value={"bbox_2d": [20, 40, 180, 360], "complete": True},
				),
			):
				report = inspect_framing({"references": [], "keyframe_artifact": artifact.name})
				self.assertEqual("assessed", report["status"])
				self.assertEqual(artifact.name, report["generation_artifact"])
				self.assertEqual([0.1, 0.1, 0.9, 0.9], report["bounds"])


class TestCreativeWorkflow(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Reference-only test",
				"product_name": "Blue product",
				"total_duration_seconds": 10,
				"delivery_width": 1280,
				"delivery_height": 720,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)
		from joymedia.services.intake.assets import create_media_asset
		from joymedia.tests.support.e2e_setup import _generate_image_bytes

		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "product-view.png",
				"content": _generate_image_bytes(),
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		created = create_media_asset("Blue product", "Product", file_name=file.name)
		self.version = created["asset_version"]
		frappe.db.set_value(
			"Asset Version",
			self.version,
			{
				"analysis_status": "Ready",
				"analysis_json": json.dumps(
					{"version": 2, "kind": "product", "description": "A blue product."}
				),
			},
		)
		self.project.append(
			"selected_media",
			{
				"reference_key": "product",
				"identity_key": "one_product",
				"reference_role": "Product",
				"asset_version": self.version,
				"label": "Blue product",
			},
		)
		self.project.save(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def batch(self, count=1):
		from joymedia.api.creative import create_product_batch

		with patch("frappe.enqueue"):
			result = create_product_batch(self.project.name, count=count, auto_render=False)
		return frappe.get_doc("Creative Batch", result["batch"])

	def test_batch_count_is_independent_of_photo_count_and_preserves_format(self):
		batch = self.batch(20)
		request = frappe.parse_json(batch.request_json)
		self.assertEqual(20, len(frappe.parse_json(batch.variants_json)))
		self.assertEqual(1, len(request["references"]))
		self.assertEqual((1280, 720, 10), (request["width"], request["height"], request["duration_seconds"]))
		self.assertEqual(20, len({v["nonce"] for v in frappe.parse_json(batch.variants_json)}))
		for count in (0, 21, True, "many"):
			with self.subTest(count=count), self.assertRaises(ValueError):
				self.batch(count)

	def test_batch_keeps_general_action_and_endpoint_references(self):
		from joymedia.api.creative import create_product_batch

		self.project.append(
			"selected_media",
			{
				"reference_key": "extraction_endpoint",
				"reference_role": "General",
				"asset_version": self.version,
				"label": "Observed tissue extraction endpoint",
			},
		)
		self.project.save(ignore_permissions=True)
		with patch("frappe.enqueue"):
			result = create_product_batch(self.project.name, auto_render=False)
		request = frappe.parse_json(frappe.get_doc("Creative Batch", result["batch"]).request_json)
		self.assertIn("extraction_endpoint", [row["reference_key"] for row in request["references"]])

	def test_heroes_rotate_and_each_video_copies_only_its_product(self):
		from joymedia.api.creative import create_product_batch
		from joymedia.services.generation.creative_batch import _create_variant

		self.project.append(
			"selected_media",
			{
				"reference_key": "second",
				"identity_key": "other_product",
				"reference_role": "Product",
				"asset_version": frappe.get_doc(
					"Asset Version",
					frappe.copy_doc(frappe.get_doc("Asset Version", self.version))
					.insert(ignore_permissions=True)
					.name,
				).name,
				"label": "Other product",
			},
		)
		self.project.save(ignore_permissions=True)
		with patch("frappe.enqueue"):
			result = create_product_batch(self.project.name, count=3, auto_render=False, hero_products="all")
		batch = frappe.get_doc("Creative Batch", result["batch"])
		heroes = [v["hero_product"] for v in frappe.parse_json(batch.variants_json)]
		self.assertEqual(["one_product", "other_product", "one_product"], heroes)
		with patch("joymedia.services.generation.creative_batch.persist_execution_pin"):
			variant = _create_variant(batch, frappe.parse_json(batch.request_json), 1, "other_product")
		self.assertEqual(["other_product"], [r.identity_key for r in variant.selected_media])
		with self.assertRaises(ValueError), patch("frappe.enqueue"):
			create_product_batch(self.project.name, hero_products=["not_selected"])

	def test_variant_reuses_qualified_pose_of_selected_character(self):
		from joymedia.api.creative import create_product_batch
		from joymedia.services.generation.creative_batch import _create_variant

		original = frappe.copy_doc(frappe.get_doc("Asset Version", self.version)).insert(
			ignore_permissions=True
		)
		pose = frappe.copy_doc(frappe.get_doc("Asset Version", self.version)).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Asset Version",
			pose.name,
			{
				"analysis_status": "Ready",
				"analysis_json": frappe.as_json(
					{
						"source_asset_version": original.name,
						"pose_qualification_version": 2,
						"qualified_pose_and_support": "standing on two visible feet",
						"qualified_pose_view": "front",
					}
				),
			},
		)
		self.project.append(
			"selected_media",
			{
				"reference_key": "mascot_front",
				"identity_key": "mascot",
				"reference_role": "Character",
				"asset_version": original.name,
			},
		)
		self.project.save(ignore_permissions=True)
		# A new batch starts from the root input project.  The qualified pose was
		# promoted by an earlier video, so it must be discovered across the family
		# rather than only from the root's selected-media rows.
		prior = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Earlier pose study",
				"product_name": self.project.product_name,
				"version_of": self.project.name,
				"owner": self.project.owner,
			}
		).insert(ignore_permissions=True)
		prior.append(
			"selected_media",
			{
				"reference_key": "mascot_standing",
				"identity_key": "mascot",
				"reference_role": "Character",
				"asset_version": pose.name,
			},
		)
		prior.save(ignore_permissions=True)
		with patch("frappe.enqueue"):
			result = create_product_batch(
				self.project.name,
				auto_render=False,
				reference_keys=["product", "mascot_front"],
			)
		batch = frappe.get_doc("Creative Batch", result["batch"])
		with patch("joymedia.services.generation.creative_batch.persist_execution_pin"):
			variant = _create_variant(batch, frappe.parse_json(batch.request_json), 0)
		self.assertEqual(
			{"product", "mascot_front", "mascot_standing"},
			{row.reference_key for row in variant.selected_media},
		)
		front = next(row for row in variant.selected_media if row.reference_key == "mascot_front")
		standing = next(row for row in variant.selected_media if row.reference_key == "mascot_standing")
		self.assertEqual(
			front.asset_version,
			frappe.parse_json(frappe.db.get_value("Asset Version", standing.asset_version, "analysis_json"))[
				"source_asset_version"
			],
		)

	def test_variant_does_not_reuse_unqualified_legacy_pose(self):
		from joymedia.api.creative import create_product_batch
		from joymedia.services.generation.creative_batch import _create_variant

		original = frappe.copy_doc(frappe.get_doc("Asset Version", self.version)).insert(
			ignore_permissions=True
		)
		pose = frappe.copy_doc(frappe.get_doc("Asset Version", self.version)).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Asset Version",
			pose.name,
			{
				"analysis_status": "Ready",
				"analysis_json": frappe.as_json(
					{
						"source_asset_version": original.name,
						"pose_and_support": "standing on two visible feet",
						"view": "front",
					}
				),
			},
		)
		self.project.append(
			"selected_media",
			{
				"reference_key": "mascot_front",
				"identity_key": "mascot",
				"reference_role": "Character",
				"asset_version": original.name,
			},
		)
		self.project.append(
			"selected_media",
			{
				"reference_key": "old_pose",
				"identity_key": "mascot",
				"reference_role": "Character",
				"asset_version": pose.name,
			},
		)
		self.project.save(ignore_permissions=True)
		with patch("frappe.enqueue"):
			result = create_product_batch(
				self.project.name,
				auto_render=False,
				reference_keys=["product", "mascot_front"],
			)
		batch = frappe.get_doc("Creative Batch", result["batch"])
		with patch("joymedia.services.generation.creative_batch.persist_execution_pin"):
			variant = _create_variant(batch, frappe.parse_json(batch.request_json), 0)
		self.assertNotIn("old_pose", {row.reference_key for row in variant.selected_media})

	def test_reviewer_notes_rewrite_only_unrendered_scripts_and_keep_history(self):
		from joymedia.services.generation.creative_batch import revise_variant, start_variant_render

		batch = self.batch()
		variants = frappe.parse_json(batch.variants_json)
		variants[0].update(
			status="Script Ready", project=self.project.name, script=sample_script(), title="First"
		)
		frappe.db.set_value("Creative Batch", batch.name, "variants_json", frappe.as_json(variants))
		notes = [{"scene": 1, "text": "Show the logo earlier."}]
		with patch("frappe.enqueue"):
			revise_variant(batch.name, 0, notes)
		variant = frappe.parse_json(frappe.db.get_value("Creative Batch", batch.name, "variants_json"))[0]
		self.assertEqual("Queued", variant["status"])
		self.assertNotIn("project", variant)
		self.assertEqual(notes, variant["revision"]["notes"])
		self.assertEqual(self.project.name, variant["history"][0]["project"])
		with self.assertRaisesRegex(ValueError, "Only a written"):
			start_variant_render(batch.name, 0)

	def test_automatic_request_freezes_existing_owner_feedback(self):
		note = {"source": "owner-feedback", "category": "Physics", "text": "Maintain visible tool contact."}
		with patch("joymedia.api.creative._review_context", return_value=[note]):
			batch = self.batch()
		self.assertEqual([note], frappe.parse_json(batch.request_json)["review_notes"])

	def test_reference_preservation_survives_batch_copy_workbook_and_native_import(self):
		from frappe.utils.file_manager import save_file

		from joymedia.api.storyboard import import_storyboard_workbook
		from joymedia.services.generation.creative_batch import _create_variant
		from joymedia.services.intake.references import preservation_modes
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.workflow = _create_workflow()
		self.project.save(ignore_permissions=True)
		file_url = frappe.db.get_value("Asset Version", self.version, "file")
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "file_name")
		for mode in ("reference_guided", "source_pixels"):
			self.project.db_set(
				"storyboard_source_json",
				frappe.as_json(
					{
						"references": [
							{
								"name": "product",
								"file": file_name,
								"role": "Product",
								"preservation_mode": mode,
							}
						]
					}
				),
			)
			batch = self.batch()
			request = frappe.parse_json(batch.request_json)
			self.assertEqual(mode, request["reference_preservation_modes"][self.version])
			with (
				patch("frappe.enqueue"),
				patch("joymedia.services.generation.creative_batch.persist_execution_pin"),
			):
				derived = _create_variant(batch, request, 0)
				self.assertEqual(mode, preservation_modes(derived)[self.version])
				file = save_file(
					"preservation-roundtrip.xlsx",
					script_workbook(sample_script(), derived),
					"Media Project",
					derived.name,
					is_private=1,
				)
				import_storyboard_workbook(derived.name, file.name, "Storyboard")
				derived.reload()
				self.assertEqual(mode, preservation_modes(derived)[self.version])

	def test_shared_settings_wait_for_native_job_and_cancel_prevents_visual_handoff(self):
		from joymedia.services.generation.creative_batch import advance_batch

		batch = self.batch()
		variants = frappe.parse_json(batch.variants_json)
		variants[0].update(project=self.project.name, status="Locations", location_job="native-places")
		batch.db_set({"status": "Rendering", "variants_json": frappe.as_json(variants)})
		with (
			patch("joymedia.services.generation.creative_batch.is_render_alive", return_value=True),
			patch("joymedia.services.generation.creative_batch._submit_visual_stage") as submit,
		):
			advance_batch(batch.name)
			submit.assert_not_called()
		with (
			patch("joymedia.services.generation.creative_batch.is_render_alive", return_value=False),
			patch("joymedia.services.keyframes.locations.missing_places", return_value={}),
			patch("joymedia.services.keyframes.locations.missing_views", return_value={}),
			patch("joymedia.services.keyframes.locations.assign_places") as assign,
			patch("joymedia.services.generation.creative_batch._submit_visual_stage") as submit,
		):
			advance_batch(batch.name)
			assign.assert_called_once()
			submit.assert_called_once()
		batch.db_set("status", "Cancelled")
		with patch("joymedia.services.generation.creative_batch._submit_visual_stage") as submit:
			advance_batch(batch.name)
			submit.assert_not_called()

	def test_generated_workbook_round_trips_through_the_existing_import_schema(self):
		from joymedia.services.planning.workbook import read_workbook

		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "generated.xlsx"
			path.write_bytes(script_workbook(sample_script(), self.project))
			parsed = read_workbook(path)
		demo = parsed["demos"][0]
		self.assertEqual("16:9", demo["metadata"]["format"])
		self.assertEqual([6, 4], [s["duration_seconds"] for s in demo["scenes"]])
		self.assertEqual(sample_script()["scenes"][0]["action"], demo["scenes"][0]["action"])
		self.assertEqual("medium", demo["scenes"][0]["shot_framing"])
		self.assertFalse(demo["scenes"][0].get("narrative_stage"))
		self.assertEqual("cinematic", parsed["brand"]["camera_style"])
		self.assertIn(sample_script()["scenes"][0]["visible_change"], demo["scenes"][0]["continuity"])
		self.assertEqual([], demo["timing_warnings"])

	def test_ai_scene_names_remain_unique_through_the_workbook(self):
		from joymedia.services.planning.creative import unique_scene_names
		from joymedia.services.planning.workbook import read_workbook

		script = sample_script()
		script["scenes"][0]["beat_name"] = "Product Use"
		script["scenes"][1]["beat_name"] = " product   use "
		original_actions = [scene["action"] for scene in script["scenes"]]
		unique_scene_names(script)
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "unique-scenes.xlsx"
			path.write_bytes(script_workbook(script, self.project))
			parsed = read_workbook(path)
		self.assertEqual(
			["Product Use", "product use (2)"],
			[scene["beat_name"] for scene in parsed["demos"][0]["scenes"]],
		)
		self.assertEqual(original_actions, [scene["action"] for scene in parsed["demos"][0]["scenes"]])

	def test_subject_travel_survives_template_import_for_shared_camera_policy(self):
		from joymedia.services.planning.camera import infer_cinematic_intent
		from joymedia.services.planning.shot_structure import authored_coverage
		from joymedia.services.planning.workbook import read_workbook

		script = sample_script()
		script["scenes"][0]["subject_motion"] = "locomotion"
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "motion.xlsx"
			path.write_bytes(script_workbook(script, self.project))
			parsed = read_workbook(path)
		coverage = authored_coverage(parsed["demos"][0]["scenes"][0])
		self.assertEqual("locomotion", coverage["subject_motion"])
		intent = infer_cinematic_intent(
			{"stage": "approach", "framing": "full", "subject_motion": coverage["subject_motion"]}
		)
		self.assertEqual("tracking", intent["behavior"])

	def test_generated_fractional_frame_timing_round_trips_without_gaps_or_lost_phases(self):
		from joymedia.services.planning.creative import fit_generated_timing
		from joymedia.services.planning.timed_actions import read_timed_actions
		from joymedia.services.planning.workbook import read_workbook

		script = sample_script()
		script["scenes"] = [copy.deepcopy(script["scenes"][0]) for _ in range(7)]
		script = fit_generated_timing(script, 30, 24)
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "frame-script.xlsx"
			path.write_bytes(script_workbook(script, self.project))
			demo = read_workbook(path)["demos"][0]
		self.assertEqual([], demo["timing_warnings"])
		self.assertAlmostEqual(30, sum(s["duration_seconds"] for s in demo["scenes"]))
		self.assertEqual(720, sum(round(s["duration_seconds"] * 24) for s in demo["scenes"]))
		for scene in demo["scenes"]:
			self.assertEqual(2, len(read_timed_actions(scene["action"], scene["duration_seconds"])))

	def test_cancellation_is_durable_and_concurrent_variant_writes_do_not_erase_progress(self):
		from joymedia.services.generation.creative_batch import _write

		batch = self.batch(2)
		first = frappe.parse_json(batch.variants_json)
		stale = copy.deepcopy(first)
		first[0]["status"] = "Script Ready"
		_write(batch.name, first, changed_index=0)
		stale[1]["status"] = "Script Ready"
		_write(batch.name, stale, changed_index=1)
		batch.reload()
		self.assertEqual("Scripts Ready", batch.status)
		self.assertEqual(
			["Script Ready", "Script Ready"], [v["status"] for v in frappe.parse_json(batch.variants_json)]
		)
		batch.db_set("status", "Cancelled")
		self.assertFalse(_write(batch.name, first, "Planning", changed_index=0))
		self.assertEqual("Cancelled", batch.reload().status)

	def test_two_variants_can_progress_while_a_third_waits_for_a_slot(self):
		from joymedia.services.generation.creative_batch import _queue_prepare

		batch = self.batch(3)
		variants = frappe.parse_json(batch.variants_json)
		variants[0]["status"] = "Rendering"
		variants[1]["status"] = "Keyframes"
		batch.db_set("variants_json", frappe.as_json(variants))
		with (
			patch("joymedia.services.generation.creative_batch.is_render_alive", return_value=False),
			patch(
				"joymedia.services.generation.creative_batch._planning_queue",
				return_value="joymedia_planning",
			),
			patch("frappe.enqueue") as enqueue,
		):
			_queue_prepare(batch.name, variants)
			enqueue.assert_not_called()
			variants[0]["status"] = "Completed"
			batch.db_set("variants_json", frappe.as_json(variants))
			_queue_prepare(batch.name, variants)
			enqueue.assert_called_once()
			self.assertEqual("joymedia_planning", enqueue.call_args.kwargs["queue"])
			self.assertEqual(f"joymedia-creative-prepare:{batch.name}:2", enqueue.call_args.kwargs["job_id"])

	def test_planning_falls_back_to_long_queue_when_no_planning_worker_is_online(self):
		from joymedia.services.generation.creative_batch import _planning_queue

		with (
			patch(
				"joymedia.services.generation.creative_batch.get_queues_timeout",
				return_value={"joymedia_planning": 3600},
			),
			patch("joymedia.services.generation.creative_batch.get_queue", return_value="planning"),
			patch("joymedia.services.generation.creative_batch.get_workers", return_value=[]),
		):
			self.assertEqual("long", _planning_queue())

	def test_planner_outage_waits_for_recovery_without_spending_creative_retry(self):
		from joymedia.services.generation.creative_batch import _defer_planner_outage, _next_prepare_index
		from joymedia.services.planning.production import PlannerUnavailableError

		variants = [{"status": "Planning", "nonce": "same-concept", "automatic_script_redraws": 0}]
		with patch("joymedia.services.generation.creative_batch.time.time", return_value=1000):
			self.assertTrue(_defer_planner_outage(variants[0], PlannerUnavailableError("connection refused")))
			self.assertEqual("Queued", variants[0]["status"])
			self.assertEqual(1060, variants[0]["retry_after"])
			self.assertIsNone(_next_prepare_index(variants))
		with patch("joymedia.services.generation.creative_batch.time.time", return_value=1061):
			self.assertEqual(0, _next_prepare_index(variants))
		self.assertEqual("same-concept", variants[0]["nonce"])
		self.assertEqual(0, variants[0]["automatic_script_redraws"])

	def test_invalid_automatic_script_gets_new_concept_with_failure_history(self):
		from joymedia.services.generation.creative_batch import _redraw_invalid_automatic_script

		variant = {"status": "Planning", "nonce": "rejected-concept"}
		failure = ValueError(
			"Automatic script remained invalid after bounded repair: "
			"Scene 1 cleans a mess that never happened on camera."
		)
		self.assertTrue(_redraw_invalid_automatic_script(variant, failure))
		self.assertEqual("Queued", variant["status"])
		self.assertNotEqual("rejected-concept", variant["nonce"])
		self.assertIn("Scene 1 cleans", variant["script_attempts"][0]["error"])
		self.assertFalse(_redraw_invalid_automatic_script(variant, ValueError("Missing product reference")))
		self.assertTrue(
			_redraw_invalid_automatic_script(
				variant, ValueError("The planner returned invalid JSON after retry: no object")
			)
		)

	def test_interrupted_planning_resumes_even_when_both_slots_are_occupied(self):
		from joymedia.services.generation.creative_batch import (
			_next_prepare_index,
			_prepare_position,
			_queue_prepare,
		)

		batch = self.batch(3)
		variants = frappe.parse_json(batch.variants_json)
		variants[0]["status"] = "Queued"
		variants[1]["status"] = "Planning"
		variants[2]["status"] = "Rendering"
		batch.db_set("variants_json", frappe.as_json(variants))
		self.assertEqual(1, _next_prepare_index(variants))
		self.assertEqual(1, _prepare_position(variants, 1))
		self.assertIsNone(_prepare_position(variants, 0))
		with (
			patch("joymedia.services.generation.creative_batch.is_render_alive", return_value=False),
			patch(
				"joymedia.services.generation.creative_batch._planning_queue",
				return_value="joymedia_planning",
			),
			patch("frappe.enqueue") as enqueue,
		):
			_queue_prepare(batch.name, variants)
			self.assertEqual(f"joymedia-creative-prepare:{batch.name}:1", enqueue.call_args.kwargs["job_id"])
			self.assertEqual(1, enqueue.call_args.kwargs["position"])

	def test_automatic_render_does_not_override_failed_keyframe_review(self):
		from joymedia.services.generation.creative_batch import advance_batch
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())

		batch = self.batch()
		request = frappe.parse_json(batch.request_json)
		request["delivery_mode"] = "assisted"
		request["auto_first_frames"] = False  # Explicit legacy assisted review path.
		batch.db_set("request_json", frappe.as_json(request))
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Keyframes")
		batch.db_set({"status": "Rendering", "variants_json": frappe.as_json([variant])})
		shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"duration_seconds": 10,
				"generation_prompt": "Act.",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Shot",
			shot.name,
			{
				"keyframe_artifact": "unqualified-reference",
				"consistency_status": "Needs Review",
				"consistency_notes": "Unsupported seated geometry",
			},
		)
		self.project.db_set("storyboard_approval_status", "Approved")
		with (
			patch(
				"joymedia.services.generation.creative_batch.partner_batch_waits_for_gpu", return_value=False
			),
			patch("joymedia.services.generation.creative_batch._stale_keyframe", return_value=False),
			patch("joymedia.services.keyframes.stage.set_keyframe_approval") as approve,
			patch.object(frappe.db, "rollback"),
		):
			advance_batch(batch.name)
			approve.assert_not_called()
		# The unqualified picture waits for a person; it is never approved automatically.
		self.assertEqual("Awaiting Review", batch.reload().status)
		variant = frappe.parse_json(batch.variants_json)[0]
		self.assertEqual("Pictures Ready", variant["status"])
		self.assertEqual({shot.name: "Unsupported seated geometry"}, variant["picture_notes"])

	def test_assisted_batch_automatically_repairs_first_frames_when_requested(self):
		from joymedia.services.generation.creative_batch import advance_batch
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())
		batch = self.batch()
		request = frappe.parse_json(batch.request_json)
		request.update(delivery_mode="assisted", auto_first_frames=True)
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Keyframes")
		batch.db_set(
			{
				"status": "Rendering",
				"request_json": frappe.as_json(request),
				"variants_json": frappe.as_json([variant]),
			}
		)
		shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"duration_seconds": 10,
				"generation_prompt": "Act.",
			}
		).insert(ignore_permissions=True)
		with (
			patch("joymedia.services.review.physical_audit.audit_frames"),
			patch("joymedia.services.generation.creative_batch._audit_rejected_first_frames") as rejected,
			patch(
				"joymedia.services.generation.creative_batch._frame_corrections",
				return_value={shot.name: ["Critical geometry: unsupported body"]},
			),
			patch(
				"joymedia.services.generation.creative_batch._start_frame_corrections", return_value=True
			) as repair,
		):
			advance_batch(batch.name)
		rejected.assert_called_once()
		repair.assert_called_once()

	def test_explicit_automatic_delivery_stops_on_unqualified_first_frames(self):
		from joymedia.services.generation.creative_batch import advance_batch
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())
		batch = self.batch()
		request = frappe.parse_json(batch.request_json)
		request.update(auto_render=True, delivery_mode="automatic")
		variant = frappe.parse_json(batch.variants_json)[0]
		from joymedia.services.generation import creative_batch

		# Scene repairs are spent: a remaining critical frame cannot be animated.
		variant.update(
			project=self.project.name,
			status="Keyframes",
			automatic_scene_rewrites=creative_batch.AUTOMATIC_SCENE_REWRITES,
		)
		batch.db_set(
			{
				"status": "Rendering",
				"request_json": frappe.as_json(request),
				"variants_json": frappe.as_json([variant]),
			}
		)
		shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"duration_seconds": 10,
				"generation_prompt": "Act.",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Shot", shot.name, {"keyframe_artifact": "generated-frame", "consistency_status": "Checking"}
		)

		with (
			patch("joymedia.services.generation.creative_batch._storyboard_with_frames") as workbook,
			patch("joymedia.services.generation.creative_batch._keyframe_ready", return_value=False),
			patch("joymedia.services.generation.creative_batch._stale_keyframe", return_value=False),
			patch("joymedia.services.keyframes.stage.set_keyframe_approval") as authorize,
			patch.object(type(self.project), "generate_video", autospec=True) as render,
			# Frame redraws are spent too: the finding is retained in the stop reason.
			patch.object(creative_batch, "AUTOMATIC_FRAME_CORRECTIONS", 0),
		):
			advance_batch(batch.name)
			workbook.assert_not_called()
			authorize.assert_not_called()
			frappe.db.set_value(
				"Shot",
				shot.name,
				{
					"consistency_status": "Needs Review",
					"consistency_notes": "Critical geometry: character pose differs from the reference.",
				},
			)
			advance_batch(batch.name)
			workbook.assert_called_once()
			authorize.assert_not_called()
			render.assert_not_called()
		result = frappe.parse_json(batch.reload().variants_json)[0]
		self.assertEqual("Needs Attention", result["status"])
		self.assertIn("Critical geometry", result["picture_notes"][shot.name])

	def test_delivery_policy_is_frozen_without_changing_site_or_other_requests(self):
		from joymedia.services.generation.automation import delivery_context
		from joymedia.services.project.context import build_project_snapshot

		with patch("joymedia.services.review.admission.freeze_policy", return_value={"version": 1}) as policy:
			with delivery_context({"delivery_mode": "automatic"}, "test-batch"):
				automatic = json.loads(build_project_snapshot(self.project)[0])
				policy.assert_called_once()
			assisted = json.loads(build_project_snapshot(self.project)[0])
		self.assertEqual("required", automatic["automatic_delivery"]["quality_review"])
		self.assertEqual({"version": 1}, automatic["visual_admission"])
		self.assertNotIn("automatic_delivery", assisted)
		self.assertEqual({"version": 1}, assisted["visual_admission"])

	def test_write_conflict_retries_next_tick_instead_of_stopping_the_video(self):
		import MySQLdb
		import pymysql

		from joymedia.services.generation.creative_batch import advance_batch

		batch = self.batch()
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Rendering", generation_request={"run": "R"})
		batch.db_set({"status": "Rendering", "variants_json": frappe.as_json([variant])})
		for error in (pymysql.err.OperationalError, MySQLdb.OperationalError):
			with self.subTest(driver=error):
				conflict = error(1020, "Record has changed since last read")
				with (
					patch("frappe.db.get_value", side_effect=conflict),
					patch.object(frappe.db, "rollback"),
				):
					advance_batch(batch.name)
				self.assertEqual("Rendering", frappe.parse_json(batch.reload().variants_json)[0]["status"])
		from joymedia.services.generation.creative_batch import _transient

		self.assertTrue(
			_transient(RuntimeError("(1020, \"Record has changed since last read in table 'tabSeries'\")"))
		)
		self.assertTrue(
			_transient(ValueError("This scene is still being rendered. Please wait until it is ready."))
		)

	def test_retry_after_failed_render_rerenders_only_scenes_without_a_take(self):
		from joymedia.services.generation.creative_batch import rerender_failed_scenes
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())
		shots = [
			frappe.get_doc(
				{
					"doctype": "Shot",
					"media_project": self.project.name,
					"shot_number": n,
					"duration_seconds": 5,
					"generation_prompt": "Act.",
				}
			).insert(ignore_permissions=True)
			for n in (1, 2)
		]
		frappe.db.set_value("Shot", shots[0].name, "selected_output_asset_version", self.version)
		variant = {"project": self.project.name}
		with (
			patch("joymedia.services.generation.takes._start_takes_run", return_value={"run": "R2"}) as takes,
			patch("joymedia.services.generation.creative_batch.pinned_execution"),
		):
			rerender_failed_scenes(variant, {"generation_pipeline": "P"})
		self.assertEqual([shots[1].name], takes.call_args.args[1])
		self.assertEqual({"run": "R2"}, variant["generation_request"])

	def test_completed_native_run_is_recovered_before_retrying_gpu_work(self):
		from joymedia.services.generation.creative_batch import rerender_failed_scenes

		variant = {"project": self.project.name, "generation_request": {"run": "R1"}}
		with (
			patch("joymedia.services.generation.creative_batch.is_automatic", return_value=True),
			patch("frappe.db.get_value", return_value="Completed"),
			patch("joymedia.services.generation.creative_batch._select_automatic_outputs") as select,
			patch("frappe.get_all", return_value=[]),
			patch("joymedia.services.generation.takes._start_takes_run") as render,
		):
			rerender_failed_scenes(variant, {"generation_pipeline": "P"})
		select.assert_called_once_with(self.project.name, "R1", variant)
		render.assert_not_called()

	def test_reviewer_accepts_a_watched_clip_and_the_note_is_kept(self):
		from joymedia.services.generation.creative_batch import accept_held_clip
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())
		shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"duration_seconds": 5,
				"generation_prompt": "Act.",
			}
		).insert(ignore_permissions=True)
		batch = self.batch()
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Rendering")
		batch.db_set("variants_json", frappe.as_json([variant]))
		with self.assertRaisesRegex(ValueError, "stopped"):
			accept_held_clip(batch.name, 0, shot.name, "Looks right.", asset_version="TAKE")
		variant["status"] = "Needs Attention"
		batch.db_set("variants_json", frappe.as_json([variant]))
		with patch("joymedia.services.generation.takes.use_reviewed_take") as use:
			accept_held_clip(batch.name, 0, shot.name, "Bear lifts the pack.", asset_version="TAKE")
		use.assert_called_once_with(self.project.name, shot.name, "TAKE", None)
		kept = frappe.parse_json(batch.reload().variants_json)[0]["reviewed_clips"]
		self.assertEqual([("TAKE", "Bear lifts the pack.")], [(r["asset_version"], r["note"]) for r in kept])

	def test_scene_notes_at_picture_review_rewrite_in_place(self):
		from joymedia.services.generation.creative_batch import revise_variant

		batch = self.batch()
		variants = frappe.parse_json(batch.variants_json)
		variants[0].update(status="Pictures Ready", project=self.project.name, script=sample_script())
		frappe.db.set_value("Creative Batch", batch.name, "variants_json", frappe.as_json(variants))
		with patch("frappe.enqueue") as enqueue:
			revise_variant(batch.name, 0, [{"scene": 2, "text": "Make it a medium shot."}])
		variant = frappe.parse_json(frappe.db.get_value("Creative Batch", batch.name, "variants_json"))[0]
		self.assertEqual("Rewriting", variant["status"])
		self.assertEqual(self.project.name, variant["project"])  # same project, pictures kept
		self.assertIn("rewrite_scenes_in_place", enqueue.call_args.args[0])

	def test_pose_only_rewrite_keeps_the_script_and_requalifies_the_named_scenes(self):
		from joymedia.services.generation import creative_batch as cb

		batch = self.batch()
		variants = frappe.parse_json(batch.variants_json)
		script = sample_script()
		variants[0].update(
			status="Rewriting",
			project=self.project.name,
			script=script,
			scene_revision={"pose_scenes": [1], "by": "Retry"},
		)
		frappe.db.set_value("Creative Batch", batch.name, "variants_json", frappe.as_json(variants))
		deferred = [{"scene": 1, "source": "x", "pose": "standing", "status": "deferred"}]
		with (
			patch("joymedia.services.planning.creative.draft_script", side_effect=AssertionError) as draft,
			patch(
				"joymedia.services.planning.pose_assets.prepare_script_pose_views", return_value=deferred
			) as prepare,
			patch("frappe.log_error"),
			# The job's error path rolls back; keep this test's uncommitted fixture.
			patch.object(frappe.db, "rollback"),
		):
			script["scenes"][0]["cast"] = script["scenes"][0].get("cast") or ["x"]
			variants[0]["script"] = script
			frappe.db.set_value("Creative Batch", batch.name, "variants_json", frappe.as_json(variants))
			cb.rewrite_scenes_in_place(batch.name, 0)
		draft.assert_not_called()
		prepare.assert_called_once()
		variant = frappe.parse_json(frappe.db.get_value("Creative Batch", batch.name, "variants_json"))[0]
		# Still no qualified pose with that support: the run stops again, with its evidence.
		self.assertEqual(("Needs Attention", "Keyframes"), (variant["status"], variant["resume_stage"]))
		self.assertIn("could not be verified", variant["error"])

	def test_an_interrupted_pose_retry_never_continues_to_old_first_frames(self):
		from joymedia.services.generation import creative_batch as cb
		from joymedia.services.workflows.comfyui import ComfyJobLostError

		batch = self.batch()
		variants = frappe.parse_json(batch.variants_json)
		script = sample_script()
		script["scenes"][0]["cast"] = script["scenes"][0].get("cast") or ["x"]
		request = frappe.parse_json(batch.request_json)
		request["delivery_mode"] = "automatic"
		variants[0].update(
			status="Rewriting",
			project=self.project.name,
			script=script,
			scene_revision={"pose_scenes": [1], "by": "Retry"},
		)
		frappe.db.set_value(
			"Creative Batch",
			batch.name,
			{"variants_json": frappe.as_json(variants), "request_json": frappe.as_json(request)},
		)
		with (
			patch(
				"joymedia.services.planning.pose_assets.prepare_script_pose_views",
				side_effect=ComfyJobLostError("ComfyUI job x disappeared from its queue and history."),
			),
			patch("frappe.log_error"),
			patch.object(frappe.db, "rollback"),
		):
			cb.rewrite_scenes_in_place(batch.name, 0)
		variant = frappe.parse_json(frappe.db.get_value("Creative Batch", batch.name, "variants_json"))[0]
		self.assertEqual(("Needs Attention", "Keyframes"), (variant["status"], variant["resume_stage"]))

	def test_reviewer_approves_pictures_or_redraws_one(self):
		from joymedia.services.generation.creative_batch import (
			approve_variant_pictures,
			redraw_variant_picture,
		)
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())
		batch = self.batch()
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Pictures Ready")
		batch.db_set({"status": "Awaiting Review", "variants_json": frappe.as_json([variant])})
		shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"duration_seconds": 10,
				"generation_prompt": "Act.",
			}
		).insert(ignore_permissions=True)
		with (
			patch("joymedia.services.keyframes.stage.generate_keyframes", return_value={"run": "R"}) as draw,
			patch("joymedia.services.generation.creative_batch.pinned_execution"),
		):
			redraw_variant_picture(batch.name, 0, shot.name)
		draw.assert_called_once_with(self.project.name, [shot.name], draw_places=False)
		self.assertEqual("Keyframes", frappe.parse_json(batch.reload().variants_json)[0]["status"])
		variant["status"] = "Pictures Ready"
		batch.db_set("variants_json", frappe.as_json([variant]))
		with self.assertRaisesRegex(ValueError, "no picture"):
			approve_variant_pictures(batch.name, 0)
		frappe.db.set_value("Shot", shot.name, "keyframe_artifact", "frame")
		with (
			patch("joymedia.services.keyframes.stage.set_keyframe_approval") as approve,
			patch(
				"joymedia.joymedia.doctype.media_project.media_project.MediaProject.generate_video",
				return_value={"run": "V"},
			),
			patch("joymedia.services.generation.creative_batch.pinned_execution"),
		):
			approve_variant_pictures(batch.name, 0)
		approve.assert_called_once_with(self.project.name, shot.name)
		self.assertEqual("Rendering", frappe.parse_json(batch.reload().variants_json)[0]["status"])

	def test_scene_prompt_retry_replaces_only_the_selected_scene_and_resumes_automatic_cut(self):
		from joymedia.services.generation.creative_batch import retry_variant_scene_with_prompt
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())
		batch = self.batch()
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Completed")
		batch.db_set({"status": "Completed", "variants_json": frappe.as_json([variant])})
		shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"duration_seconds": 10,
				"generation_prompt": "The mascot holds the exact pack.",
				"image_prompt": "Keep the approved pack frame.",
			}
		).insert(ignore_permissions=True)
		self.project.db_set("storyboard_approval_status", "Approved")
		with (
			patch("joymedia.services.generation.takes._ensure_scene_free"),
			patch(
				"joymedia.services.planning.llm.generate_shot_revision",
				return_value={
					"summary": "Use a brisk dolly-in while the mascot pulls one tissue.",
					"generation_prompt": "A brisk dolly-in as the mascot pulls one tissue.",
					"image_prompt": "must not be used for a video-only retry",
				},
			),
			patch("joymedia.services.planning.signature.compute_plan_signature", return_value="sealed"),
			patch("joymedia.services.generation.creative_batch.pinned_execution"),
			patch("joymedia.services.generation.creative_batch.delivery_context"),
			patch(
				"joymedia.services.generation.takes.regenerate_scene", return_value={"run": "RETRY-1"}
			) as render,
		):
			result = retry_variant_scene_with_prompt(
				batch.name, 0, shot.name, "Make the pull quick and add a cinematic dolly-in."
			)
		self.assertEqual("Rendering", result["status"])
		render.assert_called_once_with(self.project.name, shot.name, automatic=True)
		updated = frappe.get_doc("Shot", shot.name)
		self.assertEqual("A brisk dolly-in as the mascot pulls one tissue.", updated.generation_prompt)
		self.assertEqual("Keep the approved pack frame.", updated.image_prompt)
		self.assertIsNone(updated.selected_output_asset_version)
		state = frappe.parse_json(batch.reload().variants_json)[0]
		self.assertEqual("Rendering", state["status"])
		self.assertEqual("RETRY-1", state["generation_request"]["run"])
		self.assertEqual(shot.name, state["scene_prompt_revisions"][-1]["shot"])

	def test_retry_resumes_failed_stage_without_erasing_evidence_or_cancel_state(self):
		from joymedia.api.creative import retry_product_variant

		batch = self.batch()
		variants = frappe.parse_json(batch.variants_json)
		variants[0].update(
			status="Needs Attention",
			resume_stage="Keyframes",
			keyframe_request={"run": "original-run"},
			error="Check geometry",
		)
		batch.db_set({"status": "Needs Attention", "variants_json": frappe.as_json(variants)})
		with patch("frappe.enqueue") as enqueue:
			result = retry_product_variant(batch.name, 1)
		self.assertEqual("Keyframes", result["status"])
		self.assertIn("advance_batch", enqueue.call_args.args[0])
		self.assertEqual(f"joymedia-creative-advance:{batch.name}", enqueue.call_args.kwargs["job_id"])
		updated = frappe.parse_json(batch.reload().variants_json)[0]
		self.assertEqual({"run": "original-run"}, updated["keyframe_request"])
		batch.db_set("status", "Cancelled")
		with self.assertRaisesRegex(ValueError, "cancelled"):
			retry_product_variant(batch.name, 1)

	def test_guest_cannot_read_batch_or_create_from_another_users_project(self):
		from joymedia.api.creative import create_product_batch, get_product_batch

		batch = self.batch()
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_product_batch(batch.name)
			with self.assertRaises(frappe.PermissionError):
				create_product_batch(self.project.name)
		finally:
			frappe.set_user("Administrator")

	def test_finishing_queues_a_fresh_review_export_instead_of_reusing_an_old_output(self):
		from joymedia.services.generation.creative_batch import advance_batch

		batch = self.batch()
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Finishing")
		batch.db_set({"status": "Finishing", "variants_json": frappe.as_json([variant])})
		self.project.db_set(
			{"post_production_status": "Completed", "current_output_asset_version": self.version}
		)
		with patch("joymedia.services.editing.export_jobs.queue_project_timeline_export") as export:
			advance_batch(batch.name)
			export.assert_called_once_with(self.project.name, purpose="review")
		self.assertEqual("Exporting", frappe.parse_json(batch.reload().variants_json)[0]["status"])

	def test_automatic_narration_waits_for_the_finished_timeline(self):
		from joymedia.services.generation.creative_batch import advance_batch

		batch = self.batch()
		request = frappe.parse_json(batch.request_json)
		request.update(auto_render=True, delivery_mode="automatic")
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Finishing")
		batch.db_set(
			{
				"status": "Finishing",
				"request_json": frappe.as_json(request),
				"variants_json": frappe.as_json([variant]),
			}
		)
		self.project.db_set("post_production_status", "Completed")
		cue = {"role": "Voiceover", "scheduled": False, "shot": "SHOT-VOICE"}
		with (
			patch("joymedia.services.audio.plan.build_audio_plan", return_value=[cue]),
			patch("joymedia.services.audio.speech.generate_voiceover") as voice,
			patch("joymedia.services.editing.export_jobs.queue_project_timeline_export") as export,
		):
			advance_batch(batch.name)
		voice.assert_called_once_with(self.project.name, "SHOT-VOICE")
		export.assert_called_once_with(self.project.name, purpose="review")

	def test_failed_render_resumes_only_after_complete_native_selection_and_not_cancellation(self):
		from joymedia.services.generation.creative_batch import advance_batch

		get_value = frappe.db.get_value
		for run_status, selected, should_finish in [
			("Failed", False, False),
			("Failed", True, True),
			("Cancelled", True, False),
		]:
			with self.subTest(run_status=run_status, selected=selected):
				batch = self.batch()
				variant = frappe.parse_json(batch.variants_json)[0]
				variant.update(
					project=self.project.name, status="Rendering", generation_request={"run": "review-run"}
				)
				batch.db_set({"status": "Rendering", "variants_json": frappe.as_json([variant])})
				with (
					patch.object(
						frappe.db,
						"get_value",
						side_effect=lambda dt, *args, **kw: run_status
						if dt == "Generation Run"
						else get_value(dt, *args, **kw),
					),
					patch.object(frappe.db, "rollback"),
					patch(
						"joymedia.services.generation.creative_batch._selected_review_outputs",
						return_value=selected,
					),
					patch("joymedia.services.audio.plan.build_audio_plan", return_value=[]),
					patch(
						"joymedia.services.editing.post_production.queue_post_production_internal"
					) as finishing,
				):
					advance_batch(batch.name)
				self.assertEqual(should_finish, finishing.called)


class TestRejectedFirstFrameAudit(TestCase):
	def test_rejected_candidate_supplies_scene_repair_evidence_once(self):
		from joymedia.services.generation.creative_batch import _audit_rejected_first_frames

		shot = frappe._dict(
			name="SHOT-test", keyframe_artifact=None, consistency_status="", consistency_notes=""
		)
		candidate = frappe._dict(name="GART-rejected", frappe_file="/private/files/rejected.png")
		audited = {}
		with (
			patch.object(frappe.db, "sql", return_value=[candidate]) as query,
			patch("frappe.get_doc", return_value=shot),
			patch(
				"joymedia.services.review.physical_audit.frame_findings",
				return_value=["Critical geometry: actor passes through the table"],
			) as review,
			patch.object(frappe.db, "set_value") as save,
		):
			self.assertEqual(
				[shot.name], _audit_rejected_first_frames("project", [shot], "RUN-test", audited)
			)
			self.assertEqual([], _audit_rejected_first_frames("project", [shot], "RUN-test", audited))
		self.assertEqual("GART-rejected", audited[shot.name])
		self.assertEqual("Needs Review", shot.consistency_status)
		self.assertIn("passes through", shot.consistency_notes)
		self.assertEqual(2, query.call_count)
		review.assert_called_once()
		save.assert_called_once()


class TestUnprotectedPicture(TestCase):
	def test_selected_first_frame_supersedes_stale_generated_frame(self):
		from joymedia.services.generation import creative_batch

		shot = frappe._dict(
			name="S",
			media_project="P",
			keyframe_artifact="old",
			consistency_status="Needs Review",
			generation_inputs=[
				frappe._dict(reference_role="Product", asset_version="PACK"),
				frappe._dict(reference_role="first_frame", asset_version="FRAME"),
			],
		)
		with (
			patch("joymedia.services.generation.creative_batch._explicit_first_frame", return_value="FRAME"),
			patch("frappe.get_doc", return_value=frappe._dict(name="P")),
			patch(
				"joymedia.services.keyframes.product_review.assert_product_frame_ready",
				side_effect=ValueError("review"),
			),
		):
			self.assertFalse(creative_batch._keyframe_ready(shot))
		with (
			patch("joymedia.services.generation.creative_batch._explicit_first_frame", return_value="FRAME"),
			patch("frappe.get_doc", return_value=frappe._dict(name="P")),
			patch("joymedia.services.keyframes.product_review.assert_product_frame_ready"),
		):
			self.assertTrue(creative_batch._keyframe_ready(shot))

	def test_an_unlocked_label_is_never_ready_automatically(self):
		from joymedia.services.generation import creative_batch

		shot = frappe._dict(name="S", keyframe_artifact="A", consistency_status="Passed", keyframe_status="")
		with (
			patch("joymedia.services.generation.creative_batch._explicit_first_frame", return_value=None),
			patch(
				"frappe.db.get_value", return_value=json.dumps({"items": [], "unprotected": "paw over pack"})
			),
		):
			self.assertTrue(creative_batch._unprotected(shot))
			self.assertFalse(creative_batch._keyframe_ready(shot))
		with (
			patch("joymedia.services.generation.creative_batch._explicit_first_frame", return_value=None),
			patch("frappe.db.get_value", return_value=json.dumps({"items": [{"box": [0, 0, 1, 1]}]})),
		):
			self.assertTrue(creative_batch._keyframe_ready(shot))


class TestSelectedReviewOutputs(TestCase):
	def test_only_current_scene_owned_native_takes_allow_review_finishing(self):
		from joymedia.services.generation.creative_batch import _selected_review_outputs

		for busy, selected, member, lineage, changed, expected in [
			(False, "V", True, True, False, True),
			(True, "V", True, True, False, False),
			(False, None, True, True, False, False),
			(False, "V", False, True, False, False),
			(False, "V", True, False, False, False),
			(False, "V", True, True, True, False),
		]:
			with self.subTest(busy=busy, selected=selected, member=member, lineage=lineage, changed=changed):
				with (
					patch.object(frappe.db, "exists", return_value=busy),
					patch("frappe.get_all", return_value=["S"]),
					patch(
						"frappe.get_doc", return_value=frappe._dict(selected_output_asset_version=selected)
					),
					patch(
						"joymedia.services.generation.takes.scene_takes",
						return_value=[frappe._dict(name="V" if member else "other")],
					),
					patch.object(
						frappe.db,
						"get_value",
						side_effect=lambda dt, *a, **kw: "A"
						if dt == "Asset Version"
						else "T"
						if dt == "Generation Attempt"
						else "S"
						if lineage
						else "other",
					),
					patch("joymedia.services.review.lineage.take_direction_changed", return_value=changed),
				):
					self.assertEqual(expected, _selected_review_outputs("P"))


class TestAutomaticScriptContracts(TestCase):
	inventory: ClassVar = [{"key": "product", "role": "Product"}]
	constraints: ClassVar = {"duration_seconds": 10, "aspect_ratio": "16:9"}

	def test_unambiguous_actor_action_recovers_omitted_closing_cast(self):
		script = sample_script()
		script["scenes"][-1]["action"] = (
			"[0-2s] The bear places the product on the table.\n[2-4s] The bear turns it forward."
		)
		validated = validate_script(
			script, [*self.inventory, {"key": "bear", "role": "Character"}], self.constraints
		)
		self.assertEqual(["bear"], validated["scenes"][-1]["cast"])

	def test_static_product_packshot_does_not_add_idle_actor(self):
		script = sample_script()
		closing = script["scenes"][-1]
		closing["cast"] = ["actor"]
		closing["action"] = "[0-4s] The product is displayed with a CTA."
		with self.assertRaisesRegex(ValueError, "inactive actor"):
			validate_script(
				script,
				[*self.inventory, {"key": "actor", "role": "Character"}],
				self.constraints,
			)

	def test_one_shot_cannot_hold_a_montage_of_places(self):
		script = sample_script()
		script["scenes"][0]["action"] = (
			"[0-6s] The product is used in various situations: table, picnic, bag."
		)
		with self.assertRaisesRegex(ValueError, "montage"):
			validate_script(script, self.inventory, self.constraints)

	def test_a_group_of_strangers_in_action_or_framing_is_refused(self):
		for field, text in (
			("action", "[0-6s] The product joins the family at the picnic."),
			("visual_camera", "Medium, a family enjoying a picnic in a park."),
		):
			script = sample_script()
			script["scenes"][0][field] = text
			with self.assertRaisesRegex(ValueError, "anonymous human"):
				validate_script(script, self.inventory, self.constraints)
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The product slides across the family room table."
		self.assertTrue(validate_script(script, self.inventory, self.constraints))

	def test_names_stay_as_written_but_vietnamese_wording_does_not(self):
		from joymedia.services.planning.creative import _foreign

		self.assertFalse(_foreign("Care for your family with Gấu Shera today!"))
		self.assertTrue(_foreign("Chăm sóc cả nhà"))
		self.assertTrue(_foreign("SIÊU MỀM"))

	def test_a_family_table_is_furniture_and_the_offending_words_are_quoted(self):
		script = sample_script()
		script["scenes"][0]["visual_camera"] = "Wide shot of a family dining table."
		self.assertTrue(validate_script(script, self.inventory, self.constraints))
		script["scenes"][0]["visual_camera"] = "Wide shot of a family at the table."
		with self.assertRaisesRegex(ValueError, '"a family"'):
			validate_script(script, self.inventory, self.constraints)

	def test_a_cta_label_is_not_shown_to_viewers(self):
		from joymedia.services.planning.creative import normalize_product_wording

		script = sample_script()
		script["scenes"][-1]["on_screen_text"] = "CTA: Mua ngay"
		script["scenes"][0]["voice_over"] = "VO: Siêu mềm mịn"
		self.assertTrue(normalize_product_wording(script, []))
		self.assertEqual("Mua ngay", script["scenes"][-1]["on_screen_text"])
		self.assertEqual("Siêu mềm mịn", script["scenes"][0]["voice_over"])

	def test_a_rule_that_keeps_a_subject_still_cannot_contradict_its_movement(self):
		script = sample_script()
		inventory = [*self.inventory, {"key": "bear", "role": "Character"}]
		script["scenes"][0]["cast"] = ["bear"]
		script["scenes"][0]["action"] = (
			"[0-1s] The bear grips the product.\n[1-6s] The bear walks it along the table."
		)
		script["scenes"][0]["continuity_rules"] = "Bear remains seated."
		with self.assertRaisesRegex(ValueError, "contradicts the action"):
			validate_script(script, inventory, self.constraints)
		script["scenes"][0]["continuity_rules"] = "The product remains on the table."
		self.assertTrue(validate_script(script, inventory, self.constraints))

	def test_display_names_use_the_clients_product_name_and_never_block(self):
		from joymedia.services.planning import creative

		script = sample_script()
		titles = {"lines": ["Quảng cáo Giấy lụa Shera"] + [f"Cảnh {i}" for i in range(len(script["scenes"]))]}
		with patch("joymedia.services.planning.production._ask_planner", return_value=titles) as ask:
			creative.display_names(script, "Vietnamese", "Giấy lụa Shera")
		self.assertIn('"Giấy lụa Shera"', ask.call_args.args[0])
		self.assertEqual("Quảng cáo Giấy lụa Shera", script["display_title"])
		self.assertEqual("Cảnh 0", script["scenes"][0]["display_name"])
		failing = sample_script()
		with patch("joymedia.services.planning.production._ask_planner", side_effect=RuntimeError("down")):
			creative.display_names(failing, "Vietnamese")
		self.assertNotIn("display_title", failing)

	def test_the_format_comes_from_the_input_never_an_assumed_reel(self):
		from joymedia.services.planning.creative import _ratio_text

		self.assertEqual("9:16", _ratio_text("Dọc 9:16"))
		self.assertEqual("16:9", _ratio_text("16:9 YouTube"))
		self.assertEqual("", _ratio_text("chưa quyết định"))
		self.assertEqual("", _ratio_text(None))

	def test_a_mess_is_made_on_camera_before_it_is_cleaned(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-1s] Grip the product.\n[1-6s] Wipe the spill on the table."
		with self.assertRaisesRegex(ValueError, "never happened on camera"):
			validate_script(script, self.inventory, self.constraints)
		script["scenes"][0]["action"] = (
			"[0-1s] A cup tips over, spilling juice.\n[1-6s] Wipe the spill with the product."
		)
		self.assertTrue(validate_script(script, self.inventory, self.constraints))
		script["scenes"][0]["action"] = (
			"[0-1s] Crumbs fall onto the table.\n[1-6s] Wipe the crumbs with the product."
		)
		self.assertTrue(validate_script(script, self.inventory, self.constraints))

	def test_the_packshot_with_the_cta_is_the_last_scene(self):
		script = sample_script()
		script["scenes"][0]["beat_name"] = "Packshot and CTA"
		with self.assertRaisesRegex(ValueError, "final scene"):
			validate_script(script, self.inventory, self.constraints)

	def test_a_repeated_line_is_rewritten_without_a_new_script(self):
		from joymedia.services.planning import creative

		script = sample_script()
		for scene in script["scenes"]:
			scene["voice_over"] = "Soft and gentle."
		with patch(
			"joymedia.services.planning.production._ask_planner", return_value={"lines": ["Strong when wet."]}
		):
			self.assertTrue(creative.fresh_example_copies(script, {}))
		self.assertEqual(
			["Soft and gentle.", "Strong when wet."], [s["voice_over"] for s in script["scenes"]]
		)

	def test_film_ends_on_the_product_and_casts_supplied_characters(self):
		script = sample_script()
		script["scenes"][-1]["products"] = []
		with self.assertRaisesRegex(ValueError, "final scene must show"):
			validate_script(script, self.inventory, self.constraints)
		with self.assertRaisesRegex(ValueError, "never appears"):
			validate_script(
				sample_script(), [*self.inventory, {"key": "mascot", "role": "Character"}], self.constraints
			)
		with_character = sample_script()
		with_character["scenes"][0]["cast"] = ["mascot"]
		self.assertEqual(
			with_character,
			validate_script(
				with_character,
				[
					*self.inventory,
					{"key": "mascot", "role": "Character"},
					{"key": "optional_view", "role": "Character"},
				],
				self.constraints,
			),
		)

	def test_body_parts_need_a_cast_actor_and_scripts_stay_english(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-1s] Hands grip the product.\n[1-6s] Move it along the table."
		with self.assertRaisesRegex(ValueError, "anonymous human"):
			validate_script(script, self.inventory, self.constraints)
		script = sample_script()
		script["scenes"][0]["voice_over"] = "Giấy mềm mịn"
		with self.assertRaisesRegex(ValueError, "English"):
			validate_script(script, self.inventory, self.constraints)

	def test_prose_describes_subjects_and_editing_text_stays_out_of_action(self):
		inventory = [{"key": "pack_400", "role": "Product"}]
		script = sample_script()
		for scene in script["scenes"]:
			scene["products"] = ["pack_400"]
		script["scenes"][0]["action"] = "[0-1s] Grip pack_400.\n[1-6s] Move it along the table."
		with self.assertRaisesRegex(ValueError, "reference keys"):
			validate_script(script, inventory, self.constraints)
		script = sample_script()
		script["scenes"][-1]["action"] = (
			"[0-2s] Turn the product to face forward.\n[2-4s] On-screen text appears with the CTA."
		)
		with self.assertRaisesRegex(ValueError, "editing text"):
			validate_script(script, self.inventory, self.constraints)

	def test_timing_compiler_shortens_an_overlong_closing_presentation(self):
		from joymedia.services.planning.creative import fit_generated_timing

		script = sample_script()
		extra = copy.deepcopy(script["scenes"][0])
		extra["duration_seconds"] = 5
		script["scenes"].insert(0, extra)
		script["scenes"][-1]["duration_seconds"] = 20
		compiled = fit_generated_timing(script, 30, 24)
		self.assertAlmostEqual(6.0, compiled["scenes"][-1]["duration_seconds"], places=1)
		self.assertAlmostEqual(30.0, sum(s["duration_seconds"] for s in compiled["scenes"]), places=3)

	def test_style_names_no_subjects(self):
		script = sample_script()
		script["visual_style"] = "Soft pastel light to emphasize the cheerful mascot"
		with self.assertRaisesRegex(ValueError, "art direction only"):
			validate_script(script, self.inventory, self.constraints)

	def test_flexible_pack_is_not_written_as_a_box(self):
		inventory = [
			{
				"key": "product",
				"role": "Product",
				"views": [{"description": "Visible construction: flexible; creases."}],
			}
		]
		script = sample_script()
		script["scenes"][0]["action"] = "[0-1s] Grip the product.\n[1-6s] Peel off the film and open the box."
		with self.assertRaisesRegex(ValueError, "flexible pack"):
			validate_script(script, inventory, self.constraints)
		self.assertTrue(validate_script(sample_script(), inventory, self.constraints))

	def test_flexible_pack_wording_is_normalized_without_a_rewrite(self):
		from joymedia.services.planning.creative import normalize_product_wording

		inventory = [
			{
				"key": "product",
				"role": "Product",
				"views": [{"description": "Visible construction: flexible."}],
			}
		]
		script = sample_script()
		script["scenes"][0]["action"] = "[0-1s] Grip the tissue box.\n[1-6s] Move the boxes along the table."
		changes = normalize_product_wording(script, inventory)
		self.assertEqual(
			"[0-1s] Grip the pack.\n[1-6s] Move the packs along the table.", script["scenes"][0]["action"]
		)
		self.assertTrue(changes)
		self.assertEqual(
			[], normalize_product_wording(sample_script(), [{"key": "p", "role": "Product", "views": []}])
		)
		uncertain = [
			{
				"key": "product",
				"role": "Product",
				"views": [{"description": "A rectangular package with uncertain construction."}],
			}
		]
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] Lift the tissue box."
		normalize_product_wording(script, uncertain)
		self.assertEqual("[0-6s] Lift the pack.", script["scenes"][0]["action"])

	def test_style_subjects_are_removed_without_a_rewrite(self):
		from joymedia.services.planning.creative import normalize_product_wording

		script = sample_script()
		script["visual_style"] = "Pastel palette, soft light, to highlight the cheerful mascot."
		self.assertTrue(normalize_product_wording(script, []))
		self.assertEqual("Pastel palette, soft light", script["visual_style"])

	def test_reference_keys_in_prose_are_replaced_without_a_rewrite(self):
		from joymedia.services.planning.creative import normalize_product_wording

		inventory = [{"key": "bear", "role": "Character", "views": [{"key": "bear_front_2"}]}]
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The bear_front_2 waves at the camera."
		self.assertTrue(normalize_product_wording(script, inventory))
		self.assertEqual("[0-6s] the character waves at the camera.", script["scenes"][0]["action"])

	def test_foreign_production_text_is_translated_not_rewritten(self):
		from joymedia.services.planning import creative

		script = sample_script()
		script["scenes"][0]["voice_over"] = "Mềm mại cho cả nhà."
		with patch.object(
			creative, "translate_lines", return_value=["Soft for the whole family."]
		) as translate:
			self.assertTrue(creative.english_production_text(script))
		self.assertEqual("English", translate.call_args.args[1])
		self.assertEqual("Soft for the whole family.", script["scenes"][0]["voice_over"])
		self.assertEqual([], creative.english_production_text(sample_script()))

	def test_a_copied_example_line_is_rewritten_without_a_new_script(self):
		from joymedia.services.planning import creative

		script = sample_script()
		script["scenes"][1]["on_screen_text"] = "Mềm mại cho cả nhà!"
		constraints = {"example_voice_lines": [creative._plain("Mềm mại cho cả nhà")]}
		with patch(
			"joymedia.services.planning.production._ask_planner", return_value={"lines": ["Êm dịu mỗi ngày"]}
		):
			self.assertTrue(creative.fresh_example_copies(script, constraints))
		self.assertEqual("Êm dịu mỗi ngày", script["scenes"][1]["on_screen_text"])
		self.assertEqual([], creative.fresh_example_copies(script, constraints))

	def test_foreign_on_screen_text_is_translated_only_for_english_viewers(self):
		from joymedia.services.planning import creative

		script = sample_script()
		script["scenes"][0]["on_screen_text"] = "Mềm mại cho cả nhà"
		self.assertEqual([], creative.english_production_text(copy.deepcopy(script), "Vietnamese"))
		with patch.object(creative, "translate_lines", return_value=["Soft for the family"]):
			self.assertTrue(creative.english_production_text(script, "English"))
		self.assertEqual("Soft for the family", script["scenes"][0]["on_screen_text"])

	def test_untranslated_english_words_are_detected(self):
		from joymedia.services.planning.creative import _untranslated

		self.assertEqual({"CLOUDS"}, _untranslated("SOFT AS CLOUDS", "MỀM NHƯ MÔI CLOUDS", set()))
		self.assertEqual(set(), _untranslated("BUY SHERA NOW", "MUA SHERA NGAY", {"shera"}))

	def test_on_screen_text_awaiting_translation_is_not_rejected(self):
		script = sample_script()
		script["scenes"][-1]["on_screen_text"] = "Mua ngay hôm nay"
		constraints = {**self.constraints, "language": "English", "viewer_language": "Vietnamese"}
		self.assertTrue(validate_script(script, self.inventory, constraints))

	def test_used_material_is_never_put_back(self):
		script = sample_script()
		script["scenes"][0]["action"] = (
			"[0-1s] Grip the product.\n[1-6s] It places the used tissue back into the package."
		)
		with self.assertRaisesRegex(ValueError, "back into its container"):
			validate_script(script, self.inventory, self.constraints)

	def test_closing_presentation_stays_brief(self):
		script = sample_script()
		extra = copy.deepcopy(script["scenes"][0])
		script["scenes"].insert(0, extra)
		script["scenes"][0]["duration_seconds"] = 2
		script["scenes"][0]["action"] = "[0-2s] Grip the product and lift it."
		script["scenes"][1]["duration_seconds"] = 1
		script["scenes"][1]["action"] = "[0-1s] Grip the product and move it."
		script["scenes"][-1]["duration_seconds"] = 7
		script["scenes"][-1]["action"] = (
			"[0-2s] Turn the product to face forward.\n[2-7s] Hold the final view."
		)
		with self.assertRaisesRegex(ValueError, "closing scene lasts 7s"):
			validate_script(script, self.inventory, self.constraints)

	def test_example_voice_over_cannot_be_copied(self):
		script = sample_script()
		script["scenes"][0]["voice_over"] = "Clean every corner, every day!"
		with self.assertRaisesRegex(ValueError, "copies an example"):
			validate_script(
				script,
				self.inventory,
				{**self.constraints, "example_voice_lines": ["clean every corner every day"]},
			)
		script = sample_script()
		script["scenes"][0]["on_screen_text"] = "TWO FOR ONE!"
		with self.assertRaisesRegex(ValueError, "copies an example"):
			validate_script(
				script, self.inventory, {**self.constraints, "example_voice_lines": ["two for one"]}
			)

	def test_heuristic_findings_are_collected_for_review_instead_of_raised(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The mascot sits and looks at the product."
		notes = []
		self.assertEqual(script, validate_script(script, self.inventory, self.constraints, notes))
		self.assertTrue(any("opening cannot consist only" in note for note in notes))

	def test_examples_teach_structure_without_story_actions(self):
		from joymedia.services.planning.creative import script_exemplars

		parsed = {
			"demos": [
				{
					"metadata": {"product_name": "Soap", "usp": "Gentle\nFresh", "duration": "20s"},
					"scenes": [
						{
							"beat_name": "Hook",
							"duration_seconds": 3,
							"visual_camera": "Close-up of secret spill",
							"action": "A secret story action",
							"voice_over": "A memorable example line here",
						}
					],
				}
			]
		}
		with (
			patch("frappe.get_doc", return_value=Mock(get_full_path=lambda: "/x.xlsx")),
			patch("joymedia.services.planning.workbook.parse_storyboard_workbook", return_value=parsed),
		):
			result = script_exemplars(["file"], 0)
		self.assertNotIn("secret story action", json.dumps(result))
		self.assertNotIn("secret spill", json.dumps(result["examples"]))
		self.assertNotIn("memorable example", json.dumps(result["examples"]))
		self.assertEqual(["close_up"], result["examples"][0]["scenes"][0]["shot_sizes"])
		self.assertEqual(["action_hook"], result["examples"][0]["marketing_rhythm"])
		self.assertEqual(1, result["examples"][0]["scenes"][0]["duration_share"])
		self.assertNotIn("duration", result["examples"][0])
		self.assertEqual(["Gentle", "Fresh"], result["claims"])
		self.assertEqual(["a memorable example line here"], result["voice_lines"])

	def test_approved_examples_supply_safe_structure_without_client_workbook(self):
		from joymedia.services.planning.creative import script_exemplars

		result = script_exemplars([], 0)
		self.assertTrue(result["examples"])
		self.assertTrue(result["marketing_rhythm"])
		self.assertEqual([], result["claims"])
		serialized = json.dumps(result).lower()
		for private_word in ("shera", "auntie", "mascot", "tissue", "shirt", "cookie"):
			self.assertNotIn(private_word, serialized)

	def test_commercial_rhythm_requires_progression_not_repeated_handling(self):
		from joymedia.services.planning.creative import commercial_action_findings

		flat = [
			{"action": "[0-5s] The mascot grips the pack.", "duration_seconds": 5, "narrative_stage": "grip"},
			{
				"action": "[0-5s] The mascot grips the pack again.",
				"duration_seconds": 5,
				"narrative_stage": "grip",
			},
			{
				"action": "[0-5s] The mascot grips the pack once more.",
				"duration_seconds": 5,
				"narrative_stage": "grip",
			},
			{"action": "[0-5s] The mascot grips the pack.", "duration_seconds": 5, "narrative_stage": "grip"},
			{
				"action": "[0-5s] The product remains heroically displayed.",
				"duration_seconds": 5,
				"narrative_stage": "hero",
			},
		]
		self.assertGreaterEqual(len(commercial_action_findings(flat, 25)), 3)
		progressive = [
			{
				"action": "[0-2s] The mascot opens the pack.\n[2-5s] It extracts one sheet.",
				"duration_seconds": 5,
				"narrative_stage": "extract",
			},
			{
				"action": "[0-5s] The mascot unfolds the sheet.",
				"duration_seconds": 5,
				"narrative_stage": "unfold",
			},
			{
				"action": "[0-5s] The mascot presses the sheet against the visible surface.",
				"duration_seconds": 5,
				"narrative_stage": "detail",
			},
			{
				"action": "[0-5s] The mascot smiles at the finished result.",
				"duration_seconds": 5,
				"narrative_stage": "feel",
			},
			{
				"action": "[0-5s] The pack holds a stable hero view.",
				"duration_seconds": 5,
				"narrative_stage": "hero",
			},
		]
		self.assertEqual([], commercial_action_findings(progressive, 25))
		repeated = [
			{
				"action": "[0-5s] The mascot rubs the sheet.",
				"duration_seconds": 5,
				"narrative_stage": stage,
				"camera_move": "static",
			}
			for stage in ("extract", "detail", "feel", "inspect", "present")
		] + [
			{
				"action": "[0-5s] The product is shown.",
				"duration_seconds": 5,
				"narrative_stage": "hero",
				"camera_move": "static",
			}
		]
		findings = commercial_action_findings(repeated, 30)
		self.assertTrue(any("repeat the same" in finding for finding in findings))
		adjacent = [
			{"action": "[0-5s] The actor unfolds the sheet.", "duration_seconds": 5, "narrative_stage": stage}
			for stage in ("unfold", "detail", "feel", "present")
		] + [{"action": "[0-5s] The product is shown.", "duration_seconds": 5, "narrative_stage": "hero"}]
		self.assertTrue(
			any("repeat the same" in finding for finding in commercial_action_findings(adjacent, 25))
		)
		static_tail = [
			*progressive[:-1],
			{
				"action": "[0-5s] The pack remains on the table.",
				"duration_seconds": 5,
				"narrative_stage": "present",
				"cast": [],
			},
			{
				"action": "[0-5s] The pack remains on the table.",
				"duration_seconds": 5,
				"narrative_stage": "hero",
				"cast": [],
			},
		]
		self.assertTrue(
			any(
				"last two scenes repeat" in finding for finding in commercial_action_findings(static_tail, 30)
			)
		)

	def test_example_marketing_rhythm_classifies_vietnamese_without_exposing_it(self):
		from joymedia.services.planning.creative import marketing_job

		self.assertEqual(
			"product_response",
			marketing_job({"action": "Mascot rút một tờ giấy từ hộp."}, 1, 6),
		)
		self.assertEqual(
			"tactile_proof",
			marketing_job({"action": "Giấy thấm nhanh và lau sạch bề mặt."}, 2, 6),
		)
		self.assertEqual(
			"payoff",
			marketing_job({"action": "Nhân vật mỉm cười, nhẹ nhõm."}, 3, 6),
		)


class TestReviewerRevision(TestCase):
	def test_revision_uses_canonical_identities_without_changing_stored_pose_and_angle_bindings(self):
		from joymedia.services.planning.creative import _keep_unnoted_scenes, canonical_writer_script

		original = {
			"scenes": [
				{
					"cast": ["pose_seated"],
					"products": ["pack_side"],
					"product_view": "side",
					"action": "Fold the tissue.",
				},
				{"cast": ["unknown_child"], "products": []},
			]
		}
		inventory = [
			{"key": "mascot", "identity": "actor", "role": "Character", "views": [{"key": "pose_seated"}]},
			{"key": "pack", "identity": "product", "role": "Product", "views": [{"key": "pack_side"}]},
		]
		canonical = canonical_writer_script(original, inventory)
		self.assertEqual(["mascot"], canonical["scenes"][0]["cast"])
		self.assertEqual(["pack"], canonical["scenes"][0]["products"])
		self.assertEqual("side", canonical["scenes"][0]["product_view"])
		self.assertEqual(["unknown_child"], canonical["scenes"][1]["cast"])
		kept = _keep_unnoted_scenes(
			{"scenes": [{}, {}]},
			{"script": canonical, "notes": [{"scene": 2, "text": "Revise only this scene."}]},
		)
		self.assertEqual(["mascot"], kept["scenes"][0]["cast"])
		self.assertEqual(["pose_seated"], original["scenes"][0]["cast"])
		self.assertEqual(["pack_side"], original["scenes"][0]["products"])

	def test_notes_on_one_scene_keep_every_other_scene_verbatim(self):
		from joymedia.services.planning.creative import _keep_unnoted_scenes

		reviewed = sample_script()
		rewrite = sample_script()
		for scene in rewrite["scenes"]:
			scene["action"] = "[0-1s] Something new."
		kept = _keep_unnoted_scenes(
			copy.deepcopy(rewrite), {"script": reviewed, "notes": [{"scene": 2, "text": "x"}]}
		)
		self.assertEqual(reviewed["scenes"][0], kept["scenes"][0])
		self.assertEqual("[0-1s] Something new.", kept["scenes"][1]["action"])
		whole = _keep_unnoted_scenes(
			copy.deepcopy(rewrite), {"script": reviewed, "notes": [{"scene": None, "text": "x"}]}
		)
		self.assertEqual(rewrite["scenes"], whole["scenes"])


class TestIdentityGroups(TestCase):
	def test_views_group_and_colour_variants_stay_separate(self):
		from joymedia.services.intake import project as intake

		pictures = {"a": (1.0, [10] * 432), "b": (1.0, [200] * 432), "copy": (1.0, [11] * 432)}
		items = [
			{"file_name": "a", "label": "Pack 400_BLUE", "role": "Product"},
			{"file_name": "b", "label": "Pack 400_PINK", "role": "Product"},
			{"file_name": "b", "label": "Pack 400_PINK_front", "role": "Product"},
			{"file_name": "copy", "label": "product", "role": "Product"},
			{"file_name": "a", "label": "mascot_front", "role": "Character"},
			{"file_name": "b", "label": "mascot", "role": "Character"},
		]
		with patch.object(intake, "_image_signature", side_effect=lambda name: pictures[name]):
			keys = intake.identity_groups(items)
		self.assertEqual(keys[0], keys[3])  # a re-encoded copy joins its subject
		self.assertEqual(keys[1], keys[2])  # a named view joins its subject
		self.assertNotEqual(keys[0], keys[1])  # a colour variant is another product
		self.assertEqual(keys[4], keys[5])
		self.assertEqual("pack_400_blue", keys[0])

	def test_legacy_named_views_merge_without_overriding_explicit_identity(self):
		from unittest.mock import Mock

		from joymedia.services.intake import project as intake

		rows = [
			frappe._dict(
				reference_role="Character", reference_key="front", identity_key="front", asset_version="a"
			),
			frappe._dict(
				reference_role="Character", reference_key="side", identity_key="side", asset_version="b"
			),
			frappe._dict(
				reference_role="Character",
				reference_key="other",
				identity_key="another_actor",
				asset_version="c",
			),
		]
		project = Mock(selected_media=rows)
		files = {"a": "mascot_front.jpg", "b": "mascot.jpg", "c": "mascot_side.jpg"}

		def get_doc(doctype, name):
			if doctype == "Asset Version":
				return frappe._dict(file=name)
			return frappe._dict(file_name=files[name["file_url"]])

		with patch.object(intake.frappe, "get_doc", side_effect=get_doc):
			self.assertTrue(intake.coalesce_existing_named_views(project))
		self.assertEqual(["front", "front", "another_actor"], [r.identity_key for r in rows])
		project.save.assert_called_once_with(ignore_permissions=True)


class TestCameraDirection(TestCase):
	def test_explicit_original_photo_hero_survives_camera_variety_as_source_hold(self):
		from joymedia.services.consistency.retention import authored_static_product_hold
		from joymedia.services.planning.creative import direct_camera, normalize_static_final_packshot

		last = {
			"cast": [],
			"products": ["pack"],
			"camera_move": "static",
			"shot_framing": "full",
			"shot_angle": "eye_level",
			"narrative_stage": "hero",
			"product_view": "source",
			"subject_motion": "stationary",
			"duration_seconds": 3,
			"visual_camera": "Clean hero product shot with the original supplied product photograph.",
			"action": "[0-3s] Hero product shot of the supplied pack.",
			"continuity_rules": "The bear is seated on the rug.",
		}
		script = {"scenes": [last]}
		self.assertEqual(2, len(normalize_static_final_packshot(script)))
		direct_camera(script["scenes"], {"moves": {"hero": {"behavior": "arc"}}})
		self.assertEqual(
			("static", "full", "eye_level"),
			tuple(last[k] for k in ("camera_move", "shot_framing", "shot_angle")),
		)
		self.assertIn("No physical actor", last["continuity_rules"])
		self.assertTrue(
			authored_static_product_hold(
				{
					"references": [
						{
							"reference_role": "Product",
							"asset_version": "original",
							"reference_mode": "source_pixels",
						}
					],
					"motion_plan_json": {"actions": [{"action": last["action"].split("] ", 1)[1]}]},
				}
			)
		)
		# A real authored camera move is still executable direction.
		last.update(camera_move="dolly_out", action="[0-3s] Hero product shot of the supplied pack.")
		self.assertEqual([], normalize_static_final_packshot(script))
		direct_camera(script["scenes"])
		self.assertEqual("dolly_out", last["camera_move"])
		# The audit trail identifies a move introduced by camera variety, rather
		# than one authored by the user. A resumed revision can repair that case.
		script["camera_adjustments"] = [
			"Scene 1: camera_move static -> dolly_out (give the film enough camera movement)."
		]
		self.assertTrue(normalize_static_final_packshot(script))
		self.assertEqual("static", last["camera_move"])

	def test_camera_only_product_insert_is_normalized_without_replacing_actor_actions(self):
		from joymedia.services.planning.creative import normalize_product_camera_inserts

		script = sample_script()
		scene = script["scenes"][-1]
		scene.update(action="[0-4s] The camera zooms in on the product.", camera_move="dolly_in")
		self.assertTrue(normalize_product_camera_inserts(script))
		self.assertEqual("dolly_in", scene["camera_move"])
		self.assertIn("unchanged visible artwork", scene["action"])
		scene.update(cast=["actor"], action="[0-4s] The camera follows the actor lifting the product.")
		before = scene["action"]
		self.assertEqual([], normalize_product_camera_inserts(script))
		self.assertEqual(before, scene["action"])

	def scenes(self, *moves, framing="medium", angle="eye_level"):
		return [
			{"shot_framing": framing, "shot_angle": angle, "camera_move": move, "products": ["p"]}
			for move in moves
		]

	def test_camera_follows_what_the_subject_does(self):
		"""Reference stage preferences never override readable contact or travel."""
		from joymedia.services.planning.creative import direct_camera

		scenes = self.scenes("static", "truck_right", "pan_left", "zoom_in", "static")
		scenes[1].update(cast=["bear"], action="[0-4s] The bear pulls one tissue from the pack.")
		scenes[2].update(cast=["bear"], action="[0-4s] The bear walks to the side table.")
		scenes[3].update(cast=[], action="[0-4s] The pack rests on the table.")
		scenes[0]["narrative_stage"] = "establish"
		scenes[3]["narrative_stage"] = "detail"
		scenes[-1]["narrative_stage"] = "hero"
		changes = direct_camera(
			scenes,
			{
				"moves": {
					"establish": {"behavior": "arc"},
					"detail": {"behavior": "push_in"},
					"hero": {"behavior": "locked"},
				}
			},
		)
		self.assertEqual(
			["arc", "static", "tracking", "dolly_in", "static"], [s["camera_move"] for s in scenes]
		)
		self.assertTrue(changes)

	def test_opening_and_closing_contact_are_not_forced_into_camera_reveals(self):
		from joymedia.services.planning.creative import direct_camera

		scenes = self.scenes("arc", "dolly_out")
		for scene in scenes:
			scene.update(cast=["actor"], action="[0-4s] The actor extracts one item from the product.")
		direct_camera(scenes)
		self.assertEqual(["static", "static"], [s["camera_move"] for s in scenes])
		from joymedia.services.planning.creative import vary_against_neighbours

		self.assertEqual([], vary_against_neighbours(scenes, 1))

	def test_long_contact_commercial_gets_broad_and_hero_camera_travel(self):
		from joymedia.services.planning.creative import direct_camera

		scenes = self.scenes(*(["static"] * 6))
		for index, scene in enumerate(scenes):
			scene.update(
				cast=["bear"] if index < 5 else [],
				products=["pack"],
				narrative_stage="establish" if index == 0 else "hero" if index == 5 else "detail",
				shot_framing="wide" if index == 0 else "close_up",
				action="[0-4s] The bear pulls a sheet."
				if index < 5
				else "[0-4s] The pack remains on the table.",
			)
		direct_camera(scenes)
		# The hook moves around the cast (an arc); the finale pulls back; precise contact holds still.
		self.assertEqual("arc", scenes[0]["camera_move"])
		self.assertEqual("dolly_out", scenes[-1]["camera_move"])
		self.assertTrue(all(scene["camera_move"] == "static" for scene in scenes[1:-1]))

	def test_structured_travel_controls_camera_without_a_verb_keyword_match(self):
		from joymedia.services.planning.creative import direct_camera

		scenes = self.scenes("arc")
		scenes[0].update(
			cast=["actor"],
			subject_motion="locomotion",
			narrative_stage="establish",
			action="[0-4s] The character enters carrying the product.",
		)
		direct_camera(scenes, {"moves": {"establish": {"behavior": "arc"}}})
		self.assertEqual("tracking", scenes[0]["camera_move"])

	def test_a_rewritten_scene_is_varied_against_its_kept_neighbours(self):
		from joymedia.services.planning.creative import vary_against_neighbours

		scenes = self.scenes("dolly_in", "static", "static", "truck_right")
		for i, framing in enumerate(["wide", "medium", "close_up", "medium"]):
			scenes[i]["shot_framing"] = framing
		changes = vary_against_neighbours(scenes, 1)
		self.assertEqual(
			["dolly_in", "truck_right", "static", "truck_right"], [s["camera_move"] for s in scenes]
		)
		self.assertEqual(1, len(changes))
		self.assertEqual([], vary_against_neighbours(scenes, 3))

	def test_a_plan_already_following_the_grammar_is_left_alone(self):
		from joymedia.services.planning.creative import direct_camera

		scenes = self.scenes("arc", "truck_right", "pedestal_up", "dolly_out")
		for scene in scenes[1:3]:
			scene.update(products=["p"], cast=["bear"], action="[0-4s] The bear smiles at the camera.")
		scenes[2]["shot_framing"] = "close_up"
		self.assertEqual([], direct_camera(scenes))

	def test_viewer_text_follows_the_input_language(self):
		actorless = sample_script()
		actorless["scenes"][-1]["cast"] = []
		actorless["scenes"][-1]["action"] = "[0-4s] The mascot places the pack on the table."
		with self.assertRaisesRegex(ValueError, "describes an actor action but declares no cast"):
			validate_script(
				actorless,
				[{"key": "product", "role": "Product"}],
				{"duration_seconds": 10, "aspect_ratio": "16:9", "language": "Vietnamese"},
			)
		script = sample_script()
		script["scenes"][-1]["on_screen_text"] = "Mua ngay hôm nay"
		vi = {"duration_seconds": 10, "aspect_ratio": "16:9", "language": "Vietnamese"}
		self.assertTrue(validate_script(script, [{"key": "product", "role": "Product"}], vi))
		# Viewers hear the voice-over, so it follows their language like the on-screen text.
		script["scenes"][0]["voice_over"] = "Mềm mại như mây"
		self.assertTrue(validate_script(script, [{"key": "product", "role": "Product"}], vi))
		script["scenes"][0]["voice_over"] = "Soft for you and your family"
		with self.assertRaisesRegex(ValueError, "voice_over must be written in Vietnamese"):
			validate_script(script, [{"key": "product", "role": "Product"}], vi)
		script["scenes"][0]["voice_over"] = ""
		script["scenes"][-1]["on_screen_text"] = "Buy it now for your family"
		with self.assertRaisesRegex(ValueError, "Vietnamese"):
			validate_script(script, [{"key": "product", "role": "Product"}], vi)
		script["scenes"][-1]["on_screen_text"] = "Mua ngay hôm nay"
		with self.assertRaisesRegex(ValueError, "English"):
			validate_script(script, [{"key": "product", "role": "Product"}], {**vi, "language": "English"})


class TestAuthoredCameraMove(TestCase):
	def test_an_authored_pan_is_honoured_in_a_handling_scene_with_planned_wording(self):
		from joymedia.services.planning.camera import camera_plan

		shot = {
			"name": "S",
			"shot_number": 2,
			"duration_seconds": 5,
			"references": [{"reference_role": "Product"}, {"reference_role": "Character"}],
			"motion_plan_json": {
				"shot_structure": {
					"stage": "extract",
					"framing": "medium",
					"angle": "eye_level",
					"subject_motion": "manipulation",
					"keep_visible": [],
				},
				"camera_intent": {
					"behavior": "pan_right",
					"allow_reframe": True,
					"energy": "measured",
					"source": "authored",
				},
			},
		}
		plan = camera_plan(shot, {"shots": [{"shot": "S"}, {"shot": "T"}, {"shot": "U"}]})
		self.assertEqual("pan_right", plan["behavior"])
		self.assertIn("pans right", plan["direction"])
		self.assertIn("never hides the hand or paw contact", plan["direction"])
		self.assertNotIn("reviewed", plan["direction"])
		inferred = copy.deepcopy(shot)
		inferred["motion_plan_json"]["camera_intent"]["source"] = "inferred"
		self.assertEqual("locked", camera_plan(inferred, {"shots": [{"shot": "S"}]})["behavior"])


class TestAuthoredMoveReachesThePlan(TestCase):
	def test_wide_product_placement_is_not_misread_as_precision_extraction(self):
		from joymedia.services.planning import production

		project = frappe._dict(name="P", storyboard_source_json='{"generation_origin":"ai_director"}')
		shot = frappe._dict(shot_number=1, storyboard_beat="Open", generation_inputs=[])
		plan = {
			"motion_plan": {
				"actions": [{"action": "The mascot slides the pack onto a table."}],
				"shot_structure": {
					"stage": "extract",
					"framing": "wide",
					"angle": "eye_level",
					"subject_motion": "manipulation",
					"keep_visible": [],
				},
			},
			"notes": [],
		}
		with (
			patch("joymedia.services.planning.camera.camera_planning_rules", return_value="rules"),
			patch("joymedia.services.planning.camera.reference_camera_grammar", return_value=None),
			patch("frappe.db.count", return_value=7),
		):
			production._apply_camera_profile(project, shot, plan)
		self.assertEqual("establish", plan["motion_plan"]["shot_structure"]["stage"])
		self.assertEqual("push_in", plan["motion_plan"]["camera_intent"]["behavior"])

	def test_generated_workbook_move_is_a_proposal_for_shared_camera_policy(self):
		from joymedia.services.planning import production

		project = frappe._dict(
			storyboard_source_json=json.dumps(
				{
					"generation_origin": "ai_director",
					"selected_demo": {"scenes": [{"beat_name": "Hook", "camera_move": "arc"}]},
				}
			),
		)
		self.assertEqual("", production._authored_camera_move(project, frappe._dict(storyboard_beat="Hook")))

	def test_sheet_camera_move_becomes_the_authored_camera_intent(self):
		from joymedia.services.planning import production

		project = frappe._dict(
			name="P",
			storyboard_source_json=json.dumps(
				{"selected_demo": {"scenes": [{"beat_name": "Hook", "camera_move": "dolly_in"}]}}
			),
		)
		with patch("frappe.db.count", return_value=4):
			plan = production._apply_camera_profile(
				project, frappe._dict(storyboard_beat="Hook", shot_number=1), {"motion_plan": {}}
			)
		self.assertEqual(
			{
				"behavior": "push_in",
				"allow_reframe": True,
				"purpose": "hook",
				"energy": "brisk",
				"source": "authored",
			},
			plan["motion_plan"]["camera_intent"],
		)


class TestViewerTranslation(TestCase):
	def test_only_viewer_lines_are_translated_and_originals_are_kept(self):
		from joymedia.services.planning.creative import localize_viewer_text

		script = sample_script()
		script["scenes"][0]["voice_over"] = "Soft as a cloud."
		with patch(
			"joymedia.services.planning.production._ask_planner",
			return_value={"lines": ["Mềm như mây.", "Xem thêm"]},
		) as ask:
			localize_viewer_text(script, "Vietnamese")
		# Viewers hear the voice-over and read the on-screen text: both in their language.
		self.assertEqual("Mềm như mây.", script["scenes"][0]["voice_over"])
		self.assertEqual("Xem thêm", script["scenes"][-1]["on_screen_text"])
		self.assertEqual(["Soft as a cloud.", "See more"], script["viewer_text_source"]["lines"])
		self.assertEqual(
			"[0-1s] Grip the product.\n[1-6s] Move it along the table.", script["scenes"][0]["action"]
		)
		self.assertEqual("translator", ask.call_args.kwargs["capability"])

	def test_a_doubtful_translation_is_retried_then_flagged_for_the_reviewer(self):
		from joymedia.services.planning.creative import localize_viewer_text

		script = sample_script()
		with patch(
			"joymedia.services.planning.production._ask_planner",
			return_value={"lines": ["See more of the product now"]},
		) as ask:
			localize_viewer_text(script, "Vietnamese")
		self.assertEqual(2, ask.call_count)
		self.assertIn("See more of the product now", script["director_notes"][-1])

	def test_a_line_already_in_the_target_language_is_kept(self):
		from joymedia.services.planning.creative import localize_viewer_text

		script = sample_script()
		script["scenes"][-1]["on_screen_text"] = "MUA NGAY"
		with patch(
			"joymedia.services.planning.production._ask_planner", return_value={"lines": ["MUA NGAY"]}
		):
			localize_viewer_text(script, "Vietnamese")
		self.assertEqual("MUA NGAY", script["scenes"][-1]["on_screen_text"])
		self.assertFalse(script.get("director_notes"))

	def test_short_logo_loanword_does_not_make_vietnamese_cta_doubtful(self):
		from joymedia.services.planning.creative import localize_viewer_text

		script = sample_script()
		script["product_name"] = "Shera"
		script["scenes"][-1]["on_screen_text"] = "Logo Shera. Choose now."
		with patch(
			"joymedia.services.planning.production._ask_planner",
			return_value={"lines": ["Logo Shera. Chọn ngay!"]},
		):
			localize_viewer_text(script, "Vietnamese")
		self.assertFalse(script.get("director_notes"))

	def test_multiword_product_name_inside_vietnamese_line_is_not_flagged_as_untranslated(self):
		from joymedia.services.planning.creative import localize_viewer_text

		script = sample_script()
		script["scenes"][0]["voice_over"] = "Try Shera Premium Tissues today."
		script["scenes"][-1]["on_screen_text"] = ""
		with patch(
			"joymedia.services.planning.production._ask_planner",
			return_value={"lines": ["Thử Shera Premium Tissues hôm nay."]},
		):
			localize_viewer_text(script, "Vietnamese")
		self.assertFalse(script.get("director_notes"))

	def test_a_broken_translation_answer_is_refused(self):
		from joymedia.services.planning.creative import localize_viewer_text

		with (
			patch("joymedia.services.planning.production._ask_planner", return_value={"lines": []}),
			self.assertRaisesRegex(ValueError, "could not be translated"),
		):
			localize_viewer_text(sample_script(), "Vietnamese")
