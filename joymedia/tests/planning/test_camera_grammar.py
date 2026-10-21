import copy
import json
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.planning.camera import (
	camera_planning_rules,
	infer_cinematic_intent,
	normalize_camera_grammar,
)


class TestReferenceCameraGrammar(TestCase):
	def grammar(self):
		return {
			"version": 1,
			"sources": [{"name": "reference.mp4", "sha256": "a" * 64}],
			"notes": ["Preserve the action axis; reveal context after detail."],
			"moves": {
				"establish": {"behavior": "arc", "allow_reframe": True, "purpose": "hook"},
				"feel": {"behavior": "pull_back", "allow_reframe": True, "purpose": "reveal"},
			},
		}

	def test_reference_moves_follow_stage_without_scene_or_provider_identifiers(self):
		grammar = normalize_camera_grammar(json.dumps(self.grammar()))
		structure = {"stage": "establish", "framing": "wide", "subject_motion": "manipulation"}
		self.assertEqual("arc", infer_cinematic_intent(structure, grammar=grammar)["behavior"])
		structure["stage"] = "feel"
		self.assertEqual("pull_back", infer_cinematic_intent(structure, grammar=grammar)["behavior"])
		structure["stage"] = "extract"
		grammar["moves"]["extract"] = {"behavior": "arc"}
		self.assertEqual("locked", infer_cinematic_intent(structure, grammar=grammar)["behavior"])
		structure.update(stage="feel", framing="extreme_close_up")
		self.assertEqual("locked", infer_cinematic_intent(structure, grammar=grammar)["behavior"])

	def test_absent_profile_preserves_existing_policy(self):
		self.assertIsNone(normalize_camera_grammar(None))
		self.assertIsNone(normalize_camera_grammar(""))
		structure = {"stage": "establish", "framing": "wide", "subject_motion": "stationary"}
		self.assertEqual("push_in", infer_cinematic_intent(structure, opening=True)["behavior"])

	def test_tracking_preserves_reference_energy_without_replacing_subject_motion(self):
		grammar = normalize_camera_grammar(self.grammar())
		grammar["moves"]["establish"]["energy"] = "brisk"
		intent = infer_cinematic_intent(
			{"stage": "establish", "framing": "wide", "subject_motion": "locomotion"}, grammar=grammar
		)
		self.assertEqual("tracking", intent["behavior"])
		self.assertEqual("brisk", intent["energy"])

	def test_free_composition_can_plan_reference_reveal_without_claiming_supplied_endpoints(self):
		from joymedia.services.planning.camera import camera_plan, executable_inferred_intent

		structure = {
			"stage": "establish",
			"framing": "wide",
			"angle": "eye_level",
			"subject_motion": "stationary",
			"keep_visible": [],
		}
		intent = {"behavior": "arc", "allow_reframe": True, "purpose": "hook", "energy": "brisk"}
		self.assertEqual("push_in", executable_inferred_intent(intent, structure, set())["behavior"])
		self.assertEqual(
			intent, executable_inferred_intent(intent, structure, set(), generated_composition=True)
		)
		shot = {"shot_number": 1, "motion_plan_json": {"shot_structure": structure, "camera_intent": intent}}
		self.assertEqual("locked", camera_plan(shot, {})["behavior"])
		generated = camera_plan(shot, {}, generated_composition=True)
		self.assertEqual("arc", generated["behavior"])
		self.assertIn("depth-dependent parallax", generated["direction"])
		self.assertNotIn("reviewed viewpoints", generated["direction"])
		self.assertIn("unverified", generated["framing_evidence"])

	def test_invalid_profiles_are_rejected_instead_of_silently_falling_back(self):
		bad = []
		for field, value in [
			("version", True),
			("notes", []),
			("sources", []),
			("moves", {"made_up": {"behavior": "arc"}}),
			("moves", {"feel": None}),
			("moves", {"feel": {"behavior": "orbit_zoom"}}),
		]:
			profile = self.grammar()
			profile[field] = value
			bad.append(profile)
		profile = self.grammar()
		profile["sources"][0]["sha256"] = "unverified"
		bad.append(profile)
		for profile in bad:
			with self.subTest(profile=profile), self.assertRaises(ValueError):
				normalize_camera_grammar(profile)

	def test_normalization_does_not_mutate_authored_input(self):
		profile = self.grammar()
		before = copy.deepcopy(profile)
		result = normalize_camera_grammar(profile)
		result["notes"].append("different")
		result["moves"]["feel"]["behavior"] = "locked"
		self.assertEqual(before, profile)

	def test_reference_notes_reach_planner_only_when_enabled(self):
		brand = {"camera_style": "cinematic", "camera_grammar": self.grammar()}
		with patch("joymedia.services.intake.references.brand", return_value=brand):
			self.assertIn(brand["camera_grammar"]["notes"][0], camera_planning_rules(frappe._dict()))
			brand["camera_style"] = ""
			self.assertEqual("", camera_planning_rules(frappe._dict()))
