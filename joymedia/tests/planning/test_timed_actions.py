import unittest
from unittest.mock import patch

from joymedia.services.planning.timed_actions import read_timed_actions


class TestTimedActions(unittest.TestCase):
	def test_preserves_brisk_phases_and_explicit_hold(self):
		actions = read_timed_actions("[0-0.4s] Grip the cup.\n[0.4-1.2s] Lift it.\n[1.2-2s] Hold still.", 2)
		self.assertEqual([(0, 0.4), (0.4, 1.2), (1.2, 2)], [(a["start"], a["end"]) for a in actions])
		self.assertEqual("Lift it.", actions[1]["action"])

	def test_inline_explicit_intervals_keep_all_actions_and_exact_timing(self):
		inline = "[0-0.4s] Grip the cup. [0.4-1.2s] Lift it. [1.2-2s] Hold still."
		lines = inline.replace(". [", ".\n[")
		self.assertEqual(read_timed_actions(lines, 2), read_timed_actions(inline, 2))
		for bad in ("[0-1s] Grip. [1.2-2s] Lift.", "[0-1.2s] Grip. [1-2s] Lift."):
			with self.assertRaises(ValueError):
				read_timed_actions(bad, 2)

	def test_proposal_span_is_read_only_from_explicit_ranges(self):
		self.assertEqual(2, read_timed_actions("[0-1s] Grip. [1-2s] Lift.")[-1]["end"])
		with self.assertRaises(ValueError):
			read_timed_actions("[0-1s] Grip. [1.2-2s] Lift.")
		with self.assertRaises(ValueError):
			read_timed_actions("[0-1s] Grip.", float("nan"))

	def test_legacy_prose_is_unchanged(self):
		self.assertIsNone(read_timed_actions("Lift the cup and set it down.", 3))

	def test_bad_timing_does_not_silently_become_one_slow_action(self):
		for text in [
			"[0-1s] Grip\n[0.8-2s] Lift",
			"[0-1s] Grip\n[1.2-2s] Lift",
			"[0-3s] Grip",
			"[0-1s] Grip\nLift",
			"[0-1s] Grip",
			"[0-0s] Grip",
		]:
			with self.subTest(text=text), self.assertRaises(ValueError):
				read_timed_actions(text, 2)

	def test_schema_repair_keeps_authored_actions_instead_of_model_timing(self):
		import frappe

		from joymedia.services.planning import production as p

		transition = {
			"event": "action2",
			"before": "The cup rests on the table",
			"during": "The grip supports the rising cup",
			"after": "The supported cup is above the table",
			"forbidden": "The cup rises without support",
		}
		raw = {
			"motion_plan": {
				"actions": [],
				"scene_contract": {"transitions": [transition], "events": [{"id": "invented"}]},
			}
		}
		normalized = {
			"motion_plan": {
				"actions": [{"start": 0, "end": 2, "action": "Move slowly."}],
				"shot_structure": {"subject_motion": "manipulation"},
			},
			"setting_prompt": "table",
			"notes": [],
		}
		authored = read_timed_actions("[0-0.4s] Grip the cup.\n[0.4-2s] Lift the cup briskly.", 2)
		with (
			patch.object(p, "build_planning_prompt", return_value="generic plan"),
			patch.object(p, "_ask_planner", return_value=raw) as planner,
			patch.object(p, "translate", side_effect=lambda text, project: text),
			patch.object(p, "english_roles", side_effect=lambda text, refs, product: text),
			patch.object(
				p,
				"normalize_production_shot",
				side_effect=[frappe.ValidationError("image prompt too long"), normalized],
			),
			patch.object(p, "audio_direction", return_value=""),
		):
			plan = p._timed_sheet_plan(
				frappe._dict(product_name="cup"),
				frappe._dict(duration_seconds=2, shot_number=1),
				{},
				[],
				{"reference_keys": ["cup"], "setting_prompt": "table", "notes": []},
				authored,
				previous_end_state="The displaced prop remains on its side.",
			)
		self.assertIn("The displaced prop remains on its side.", planner.call_args.args[0])
		self.assertEqual(2, planner.call_count)
		self.assertIn('"id": "action2", "description": "Lift the cup briskly."', planner.call_args.args[0])
		self.assertEqual(authored, plan["motion_plan"]["actions"])
		self.assertEqual(["cup"], plan["reference_keys"])
		self.assertIn("briskly", plan["video_prompt"])
		self.assertNotIn("slowly", plan["video_prompt"])
		events = raw["motion_plan"]["scene_contract"]["events"]
		self.assertEqual([(0, 0.4), (0.4, 2)], [(e["start"], e["end"]) for e in events])
		self.assertEqual(["action1"], events[1]["after"])
		self.assertEqual(authored[1]["action"], events[1]["description"])
		self.assertEqual([transition], raw["motion_plan"]["scene_contract"]["transitions"])


class TestInferredCameraPolicy(unittest.TestCase):
	def test_static_authored_hold_survives_an_empty_model_motion_prompt(self):
		import frappe

		from joymedia.services.planning import production as p

		raw = {
			"image_prompt": "One product resting on the table.",
			"video_prompt": "",
			"motion_plan": {
				"shot_structure": {
					"stage": "hero",
					"framing": "medium",
					"angle": "eye_level",
					"subject_motion": "stationary",
					"keep_visible": [],
				}
			},
		}
		action = "The original product remains still with its artwork intact."
		with (
			patch.object(p, "_ask_planner", return_value=raw) as ask,
			patch.object(p, "translate", side_effect=lambda text, project: text),
			patch.object(p, "english_roles", side_effect=lambda text, refs, product: text),
			patch.object(p, "audio_direction", return_value=""),
			patch("joymedia.services.planning.camera.camera_planning_rules", return_value=""),
			patch.object(frappe.db, "count", return_value=2),
		):
			plan = p._timed_sheet_plan(
				frappe._dict(name="P", product_name="product"),
				frappe._dict(duration_seconds=4, shot_number=2),
				{},
				[],
				{"reference_keys": [], "setting_prompt": "table", "notes": []},
				[{"start": 0, "end": 4, "action": action}],
			)
		self.assertEqual(action, plan["video_prompt"])
		ask.assert_called_once()

	def test_invalid_model_camera_cannot_override_the_structural_policy(self):
		import frappe

		from joymedia.services.planning import production as p

		raw = {
			"image_prompt": "One cup on a tabletop.",
			"video_prompt": "The cup remains still.",
			"motion_plan": {
				"camera_intent": {"behavior": "push_in", "purpose": "present"},
				"shot_structure": {
					"stage": "hero",
					"framing": "medium",
					"angle": "eye_level",
					"subject_motion": "stationary",
					"keep_visible": [],
				},
			},
		}
		with (
			patch.object(p, "_ask_planner", return_value=raw) as planner,
			patch.object(p, "translate", side_effect=lambda text, project: text),
			patch.object(p, "english_roles", side_effect=lambda text, refs, product: text),
			patch.object(p, "audio_direction", return_value=""),
			patch(
				"joymedia.services.planning.camera.camera_planning_rules", return_value="structured policy"
			),
			patch.object(frappe.db, "count", return_value=1),
		):
			plan = p._timed_sheet_plan(
				frappe._dict(name="P", product_name="cup"),
				frappe._dict(duration_seconds=2, shot_number=1),
				{"shot_framing": "wide", "shot_angle": "eye_level", "narrative_stage": "establish"},
				[],
				{"reference_keys": [], "setting_prompt": "table", "notes": []},
				[{"start": 0, "end": 2, "action": "The cup remains still."}],
			)
		planner.assert_called_once()
		self.assertIn("No advertised package belongs in this opening", planner.call_args.args[0])
		self.assertNotIn(p._locked_product_opening_rule(), planner.call_args.args[0])
		self.assertEqual("wide", plan["motion_plan"]["shot_structure"]["framing"])
		self.assertEqual("establish", plan["motion_plan"]["shot_structure"]["stage"])
		self.assertEqual(plan["motion_plan"]["camera_intent"]["purpose"], "hook")
		self.assertEqual(plan["motion_plan"]["actions"][0]["action"], "The cup remains still.")


class TestAuthoredCoverage(unittest.TestCase):
	def test_typed_coverage_is_optional_and_invalid_values_fail(self):
		from joymedia.services.planning.shot_structure import authored_coverage

		self.assertEqual({}, authored_coverage({}))
		self.assertEqual(
			{"framing": "full", "stage": "feel"},
			authored_coverage({"shot_framing": "full", "narrative_stage": "feel"}),
		)
		with self.assertRaises(ValueError):
			authored_coverage({"shot_framing": "arbitrary crop"})
		with self.assertRaises(ValueError):
			authored_coverage({"subject_motion": "invented"})

	def test_schema_repair_keeps_the_original_source_context(self):
		import frappe

		from joymedia.services.planning import production as p

		raw = {
			"image_prompt": "One cup.",
			"motion_plan": {
				"shot_structure": {
					"stage": "inspect",
					"framing": "close_up",
					"angle": "eye_level",
					"subject_motion": "stationary",
					"keep_visible": [],
				}
			},
		}
		plan = {"motion_plan": raw["motion_plan"], "setting_prompt": "table", "notes": []}
		with (
			patch.object(p, "_ask_planner", side_effect=[raw, raw]) as ask,
			patch.object(p, "normalize_production_shot", side_effect=[ValueError("schema"), plan]),
			patch.object(p, "translate", side_effect=lambda x, *a: x),
			patch.object(p, "english_roles", side_effect=lambda x, *a: x),
			patch.object(p, "audio_direction", return_value=""),
		):
			p._timed_sheet_plan(
				frappe._dict(product_name="cup"),
				frappe._dict(shot_number=1, duration_seconds=2),
				{"camera": "AUTHORED WIDE ROOM"},
				[],
				{"reference_keys": [], "setting_prompt": "SAME ROOM", "notes": []},
				[{"start": 0, "end": 2, "action": "Lift the cup."}],
			)
		for call in ask.call_args_list:
			self.assertIn("AUTHORED WIDE ROOM", call.args[0])
			self.assertIn("SAME ROOM", call.args[0])
			self.assertIn("Lift the cup.", call.args[0])
			self.assertEqual(1, call.args[0].count("Optional motion_plan.shot_structure describes"))
		self.assertNotIn('"events":', ask.call_args_list[1].args[0].split("INVALID PLAN:")[1])
