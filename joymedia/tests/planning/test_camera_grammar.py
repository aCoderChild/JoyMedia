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
