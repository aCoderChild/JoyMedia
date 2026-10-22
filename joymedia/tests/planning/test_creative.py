import copy
import json
import tempfile
from pathlib import Path
from typing import ClassVar
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

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


class TestOpeningTextCrossCheck(TestCase):
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
			[
				row["quote"]
				for row in _filter_unsubstantiated_camera_issues(findings, script)["issues"]
			],
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
		self.assertEqual(6, schema["properties"]["scenes"]["minItems"])
		action_rule = schema["properties"]["scenes"]["items"]["properties"]["action"]["description"]
		self.assertIn("Combine approach/reach with acquisition", action_rule)

	def test_passive_opening_requires_an_object_action(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The mascot sits and looks at the product."
		with self.assertRaisesRegex(ValueError, "opening cannot consist only"):
			validate_script(script, self.inventory, self.constraints)

	def test_preparatory_reach_cannot_consume_an_entire_action_shot(self):
		script = sample_script()
		for action in (
			"[0-6s] The mascot reaches toward the product.",
			"[0-6s] The mascot reaches toward the table where the product is placed.",
		):
			with (
				self.subTest(action=action),
				self.assertRaisesRegex(ValueError, "no completed object or material action"),
			):
				script["scenes"][0]["action"] = action
				validate_script(script, self.inventory, self.constraints)
		script["scenes"][0]["action"] = (
			"[0-1s] The mascot reaches toward the product.\n[1-6s] The mascot grips and lifts the product."
		)
		self.assertEqual(script, validate_script(script, self.inventory, self.constraints))

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

	def test_camera_only_phase_cannot_replace_product_action(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The camera pans over the product."
		with self.assertRaisesRegex(ValueError, "Move camera movement out of Action"):
			validate_script(script, self.inventory, self.constraints)

	def test_camera_sentence_is_removed_when_a_real_timed_action_remains(self):
		script = sample_script()
		script["scenes"][0]["action"] = (
			"[0-1s] The camera pushes in. Grip the product.\n"
			"[1-6s] Move it along the table."
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

	def test_unanchored_cleaning_and_anonymous_actor_are_rejected(self):
		script = sample_script()
		script["scenes"][0]["action"] = "[0-6s] The product wipes dust from a shelf."
		with self.assertRaisesRegex(ValueError, "cleaning, fluid"):
			validate_script(script, self.inventory, {**self.constraints, "action_reference_observations": []})
		script["scenes"][0]["action"] = "[0-6s] An off-screen hand places the product on the table."
		with self.assertRaisesRegex(ValueError, "anonymous human"):
			validate_script(script, self.inventory, self.constraints)

	def test_schema_descriptions_reach_model_context_as_well_as_the_decoder(self):
		from joymedia.services.planning.production import _request_planner

		schema = {
			"type": "object",
			"properties": {"value": {"type": "string", "description": "A semantic field instruction."}},
			"required": ["value"],
			"additionalProperties": False,
		}
		response = Mock(ok=True)
		response.json.return_value = {"choices": [{"message": {"content": '{"value":"done"}'}}]}
		with (
			patch(
				"joymedia.services.runtime.endpoints.endpoint",
				return_value=frappe._dict(base_url="http://planner/v1", model="configured", timeout=30),
			),
			patch("joymedia.services.planning.plan_parsing._completion_budget", return_value=100),
			patch("joymedia.services.planning.production.requests.post", return_value=response) as post,
		):
			_request_planner("Write the object.", system="JSON only.", max_tokens=100, response_schema=schema)
		payload = post.call_args.kwargs["json"]
		self.assertIn("A semantic field instruction.", payload["messages"][0]["content"])
		self.assertEqual(schema, payload["response_format"]["json_schema"]["schema"])

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
			batch = Mock(name="batch", status="Needs Attention", variants_json=json.dumps([variant]))
			batch.name = "BATCH"
			with (
				self.subTest(script=script),
				patch("frappe.get_doc", return_value=batch),
				patch.object(frappe.cache, "lock"),
				patch.object(frappe.db, "commit"),
				patch.object(frappe.db, "set_value") as save,
				patch("frappe.enqueue"),
			):
				retry_product_variant(batch.name, 1)
				retried = json.loads(save.call_args.args[2]["variants_json"])[0]
				if script:
					self.assertEqual("old", retried["nonce"])
					self.assertEqual(script, retried["script"])
				else:
					self.assertNotEqual("old", retried["nonce"])
					self.assertEqual(
						[{"nonce": "old", "error": "Rejected draft"}], retried["script_attempts"]
					)

	def test_gallery_views_remain_one_identity_and_can_be_selected_by_scene(self):
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
			scene["products"] = ["back"]
		self.assertEqual(
			["back"], validate_script(script, inventory, self.constraints)["scenes"][0]["products"]
		)
		script["scenes"][0]["products"] = ["front", "back"]
		with self.assertRaisesRegex(ValueError, "one view per identity"):
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
				"views": [{"description": "Blue product"}],
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
		self.assertIn("Keep the original connected proportions.", last.args[0])
		self.assertNotIn("Prior version observation.", last.args[0])
		self.assertIn("PRIMARY USER DIRECTION:", last.kwargs["system"])
		self.assertIn("concrete supplied view key", last.kwargs["system"])
		self.assertIn("multi-scene", last.kwargs["system"])
		self.assertEqual("writer", last.kwargs["capability"])
		self.assertIn("scenes", last.kwargs["response_schema"]["properties"])

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

	def test_automatic_writer_never_renders_a_draft_with_unresolved_findings(self):
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
			self.assertRaisesRegex(ValueError, "unresolved causal"),
		):
			draft_script(project, nonce="strict", require_clean=True)
		self.assertEqual(6, writer.call_count)
		evidence.assert_called_once()

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
		self.assertEqual(["product", "product_side"], choices)
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

	def test_automatic_render_does_not_override_failed_keyframe_review(self):
		from joymedia.services.generation.creative_batch import advance_batch
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())

		batch = self.batch()
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
		with (
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

	def test_explicit_automatic_delivery_continues_after_first_frames(self):
		from contextlib import nullcontext

		from joymedia.services.generation.automation import current_delivery
		from joymedia.services.generation.creative_batch import advance_batch
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())
		batch = self.batch()
		request = frappe.parse_json(batch.request_json)
		request.update(auto_render=True, delivery_mode="automatic")
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
		frappe.db.set_value(
			"Shot", shot.name, {"keyframe_artifact": "generated-frame", "consistency_status": "Checking"}
		)

		def render(project):
			self.assertEqual("automatic", current_delivery()["mode"])
			return {"run": "automatic-run", "status": "Queued"}

		with (
			patch("joymedia.services.generation.creative_batch._storyboard_with_frames") as workbook,
			patch(
				"joymedia.services.generation.creative_batch._keyframe_ready",
				side_effect=AssertionError("No manual gate"),
			),
			patch(
				"joymedia.services.generation.creative_batch.pinned_execution",
				side_effect=lambda *a: nullcontext(),
			),
			patch("joymedia.services.keyframes.stage.set_keyframe_approval") as authorize,
			patch.object(type(self.project), "generate_video", autospec=True, side_effect=render),
		):
			advance_batch(batch.name)
			workbook.assert_not_called()
			authorize.assert_not_called()
			frappe.db.set_value("Shot", shot.name, "consistency_status", "Passed")
			advance_batch(batch.name)
			workbook.assert_called_once()
			authorize.assert_called_once()
		result = frappe.parse_json(batch.reload().variants_json)[0]
		self.assertEqual("Rendering", result["status"])
		self.assertEqual("deferred", result["frame_authorization"]["quality_review"])
		self.assertIsNone(current_delivery())

	def test_delivery_policy_is_frozen_without_changing_site_or_other_requests(self):
		from joymedia.services.generation.automation import delivery_context
		from joymedia.services.project.context import build_project_snapshot

		with patch("joymedia.services.review.admission.freeze_policy", return_value={"version": 1}) as policy:
			with delivery_context({"delivery_mode": "automatic"}, "test-batch"):
				automatic = json.loads(build_project_snapshot(self.project)[0])
				policy.assert_not_called()
			assisted = json.loads(build_project_snapshot(self.project)[0])
		self.assertEqual("deferred", automatic["automatic_delivery"]["quality_review"])
		self.assertNotIn("visual_admission", automatic)
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

		self.assertTrue(_transient(RuntimeError("(1020, \"Record has changed since last read in table 'tabSeries'\")")))

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


class TestUnprotectedPicture(TestCase):
	def test_selected_first_frame_supersedes_stale_generated_frame(self):
		from joymedia.services.generation import creative_batch

		shot = frappe._dict(name="S", keyframe_artifact="old", consistency_status="Needs Review")
		with patch("joymedia.services.generation.creative_batch._explicit_first_frame", return_value="source"):
			self.assertTrue(creative_batch._keyframe_ready(shot))

	def test_an_unlocked_label_is_never_ready_automatically(self):
		from joymedia.services.generation import creative_batch

		shot = frappe._dict(name="S", keyframe_artifact="A", consistency_status="Passed", keyframe_status="")
		with (
			patch("joymedia.services.generation.creative_batch._explicit_first_frame", return_value=None),
			patch("frappe.db.get_value", return_value=json.dumps({"items": [], "unprotected": "paw over pack"})),
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
		script["scenes"][0]["action"] = (
			"[0-1s] The bear grips the product.\n[1-6s] The bear walks it along the table."
		)
		script["scenes"][0]["continuity_rules"] = "Bear remains seated."
		with self.assertRaisesRegex(ValueError, "contradicts the action"):
			validate_script(script, self.inventory, self.constraints)
		script["scenes"][0]["continuity_rules"] = "The product remains on the table."
		self.assertTrue(validate_script(script, self.inventory, self.constraints))

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
							"visual_camera": "Close-up",
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
		self.assertEqual(["Gentle", "Fresh"], result["claims"])
		self.assertEqual(["a memorable example line here"], result["voice_lines"])


class TestReviewerRevision(TestCase):
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


class TestCameraDirection(TestCase):
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

	def test_generated_workbook_move_is_not_treated_as_client_authored(self):
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

	def test_a_broken_translation_answer_is_refused(self):
		from joymedia.services.planning.creative import localize_viewer_text

		with (
			patch("joymedia.services.planning.production._ask_planner", return_value={"lines": []}),
			self.assertRaisesRegex(ValueError, "could not be translated"),
		):
			localize_viewer_text(sample_script(), "Vietnamese")
