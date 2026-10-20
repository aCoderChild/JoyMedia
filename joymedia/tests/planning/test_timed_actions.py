import unittest
from unittest.mock import patch

from joymedia.services.planning.timed_actions import read_timed_actions


class TestTimedActions(unittest.TestCase):
	def test_preserves_brisk_phases_and_explicit_hold(self):
		actions = read_timed_actions("[0-0.4s] Grip the cup.\n[0.4-1.2s] Lift it.\n[1.2-2s] Hold still.", 2)
		self.assertEqual([(0, 0.4), (0.4, 1.2), (1.2, 2)], [(a["start"], a["end"]) for a in actions])
		self.assertEqual("Lift it.", actions[1]["action"])

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

	def test_sheet_keeps_authored_actions_instead_of_model_timing(self):
		import frappe

		from joymedia.services.planning import production as p

		raw = {"motion_plan": {"actions": []}}
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
			patch.object(p, "_ask_planner", return_value=raw),
			patch.object(p, "translate", side_effect=lambda text, project: text),
			patch.object(p, "english_roles", side_effect=lambda text, refs, product: text),
			patch.object(p, "normalize_production_shot", return_value=normalized),
			patch.object(p, "audio_direction", return_value=""),
		):
			plan = p._timed_sheet_plan(
				frappe._dict(product_name="cup"),
				frappe._dict(duration_seconds=2, shot_number=1),
				{},
				[],
				{"reference_keys": ["cup"], "setting_prompt": "table", "notes": []},
				authored,
			)
		self.assertEqual(authored, plan["motion_plan"]["actions"])
		self.assertEqual(["cup"], plan["reference_keys"])
		self.assertIn("briskly", plan["video_prompt"])
		self.assertNotIn("slowly", plan["video_prompt"])
		events = raw["motion_plan"]["scene_contract"]["events"]
		self.assertEqual([(0, 0.4), (0.4, 2)], [(e["start"], e["end"]) for e in events])
		self.assertEqual(["action1"], events[1]["after"])
		self.assertEqual(authored[1]["action"], events[1]["description"])


class TestInferredCameraPolicy(unittest.TestCase):
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
				{},
				[],
				{"reference_keys": [], "setting_prompt": "table", "notes": []},
				[{"start": 0, "end": 2, "action": "The cup remains still."}],
			)
		planner.assert_called_once()
		self.assertEqual(plan["motion_plan"]["camera_intent"]["purpose"], "hook")
		self.assertEqual(plan["motion_plan"]["actions"][0]["action"], "The cup remains still.")
