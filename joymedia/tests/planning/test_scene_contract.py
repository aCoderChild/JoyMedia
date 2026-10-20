import copy
import json
import math
from unittest import TestCase

import frappe

from joymedia.services.planning.plan_parsing import _normalized_motion_plan, _rescale_motion_plan
from joymedia.services.planning.prompts import compile_segment_prompt_from_snapshot
from joymedia.services.planning.scene_contract import instruction, read_contract, review_questions


def example():
	return {"scene_contract": {
		"version": 1,
		"entities": [{"id": k, "label": v} for k, v in (
			("actor", "the operator"), ("part", "the operator's gripper"),
			("vessel", "the vessel"), ("material", "the liquid"))],
		"relations": [
			{"kind": "attached_to", "subject": "part", "object": "actor"},
			{"kind": "flows_from", "subject": "material", "object": "vessel"}],
		"events": [
			{"id": "tilt", "description": "The vessel tilts", "start": 0, "end": 1, "after": []},
			{"id": "flow", "description": "Liquid exits the rim", "start": 1, "end": 3, "after": ["tilt"]}],
	}}


class TestSceneContract(TestCase):
	def test_legacy_plans_remain_unchanged(self):
		for plan in (None, {}, "", '{"actions": []}', []):
			self.assertIsNone(read_contract(plan))
			self.assertEqual(instruction(plan), "")

	def test_normalization_is_idempotent_and_preserves_contract(self):
		plan = _normalized_motion_plan(example(), 3, "Move")
		self.assertEqual(plan, _normalized_motion_plan(plan, 3, "Move"))
		self.assertEqual(read_contract(plan), read_contract(json.dumps(plan)))

	def test_rescale_updates_event_times_and_preserves_sources(self):
		shot = {"duration_seconds": 6, "motion_plan": _normalized_motion_plan(example(), 3, "Move")}
		_rescale_motion_plan(shot, 3)
		self.assertEqual(read_contract(shot["motion_plan"], 6)["events"][1]["end"], 6)
		self.assertEqual(shot["motion_plan"]["scene_contract"]["relations"], example()["scene_contract"]["relations"])

	def test_continuation_keeps_sources_without_replaying_prior_cause(self):
		text = instruction(example(), 3, 1, 3)
		self.assertIn("liquid originates only from the vessel", text)
		self.assertIn("Liquid exits the rim", text)
		self.assertNotIn("vessel tilts", text)

	def test_future_event_is_not_in_first_segment(self):
		self.assertNotIn("Liquid exits", instruction(example(), 3, 0, 1))

	def test_contract_has_no_case_or_model_identifiers(self):
		text = instruction(example(), 3)
		self.assertIn("gripper stays connected", text)
		for word in ("shera", "bear", "minimax", "comfy", "tissue"):
			self.assertNotIn(word, text.casefold())

	def test_independent_relation_and_event_order_questions(self):
		questions = review_questions(example(), 3)
		self.assertEqual(len(questions), 3)
		self.assertIn("BEFORE", questions[-1][0])

	def test_invalid_contracts_fail_before_generation(self):
		base = example()["scene_contract"]
		mutations = [
			lambda c: c.update(version=True), lambda c: c.update(version=2),
			lambda c: c.update(entities=c["entities"] * 5),
			lambda c: c["entities"].append(c["entities"][0]),
			lambda c: c["entities"][0].update(id="bad id"),
			lambda c: c["entities"][0].update(label=""),
			lambda c: c["relations"][0].update(object="missing"),
			lambda c: c["relations"][0].update(kind="invented"),
			lambda c: c["relations"][0].update(object="part"),
			lambda c: c["events"][1].update(after=["missing"]),
			lambda c: c["events"][0].update(after=["flow"]),
			lambda c: c["events"][1].update(start=0.5),
			lambda c: c["events"][1].update(end=4),
			lambda c: c["events"][0].update(end=math.nan),
			lambda c: c["events"][0].update(start=True),
			lambda c: c["events"][0].update(start=-1),
			lambda c: c["events"][0].update(end=0),
			lambda c: c["events"][0].update(after="tilt"),
		]
		for mutate in mutations:
			with self.subTest(mutation=mutate):
				contract = copy.deepcopy(base)
				mutate(contract)
				with self.assertRaises(ValueError):
					read_contract({"scene_contract": contract}, 3)

	def test_cycles_and_multiple_owners_are_rejected(self):
		for row in (
			{"kind": "attached_to", "subject": "actor", "object": "part"},
			{"kind": "attached_to", "subject": "part", "object": "vessel"},
		):
			plan = example()
			plan["scene_contract"]["relations"].append(row)
			with self.assertRaises(ValueError):
				read_contract(plan)

	def test_frozen_segment_compilation_uses_same_contract(self):
		shot = frappe._dict(name="S", shot_number=1, generation_prompt="Move.",
			motion_plan_json=json.dumps(example()), duration_seconds=3, references=[])
		project = frappe._dict(references=[], global_instructions="", generation_mode="Multi-shot")
		for count in (1, 2):
			prompt = compile_segment_prompt_from_snapshot(shot, project, count, count,
				segment_start_frame=24, segment_effective_frames=48, fps=24)
			self.assertIn("liquid originates only from the vessel", prompt)
			self.assertEqual(prompt.count("Physical staging:"), 1)
			if count == 2:
				self.assertNotIn("The vessel tilts", prompt)

class TestObservableStaging(TestCase):
	def test_opening_and_motion_have_separate_authored_requirements(self):
		from joymedia.services.planning.scene_contract import opening_instruction
		from joymedia.services.review.temporal import SequenceCheck, batches, claims_for

		plan = {"scene_contract": {"version": 1, "checks": [
			{"id": "fit", "scope": "opening", "claim": "The operator is behind the support plane."},
			{"id": "cause", "scope": "sequence", "claim": "The gripper bumps rather than grasps the vessel."}]}}
		opening = opening_instruction(plan, 3)
		self.assertIn("behind the support", opening)
		self.assertNotIn("bumps", opening)
		self.assertIn("bumps", instruction(plan, 3))
		self.assertNotIn("behind the support", instruction(plan, 3))
		claims = claims_for(plan, 3, "Move")
		check = SequenceCheck([], [{"time": i} for i in range(4)], claims, {})
		windows = [indices for indices, group in batches(check) if group[0]["id"] == "check.fit"]
		self.assertEqual(windows, [(0,)])

	def test_bad_scopes_duplicate_ids_and_excess_checks_are_rejected(self):
		for checks in [
			[{"id": "a", "scope": "invented", "claim": "A claim"}],
			[{"id": "a", "scope": "opening", "claim": "A claim"}] * 2,
			[{"id": f"c{i}", "scope": "opening", "claim": "A claim"} for i in range(9)],
		]:
			with self.assertRaises(ValueError):
				read_contract({"scene_contract": {"version": 1, "checks": checks}})

class TestSupportAndProportions(TestCase):
	def plan(self):
		return {"scene_contract": {"version": 1, "entities": [
			{"id": "actor", "label": "the seated operator"},
			{"id": "seat", "label": "the chair seat below the work surface"},
			{"id": "vessel", "label": "the vessel"},
			{"id": "liquid", "label": "the liquid"}], "relations": [
			{"kind": "supported_by", "subject": "actor", "object": "seat"},
			{"kind": "flows_from", "subject": "liquid", "object": "vessel"}],
			"proportions": [{"subject": "vessel", "reference": "actor", "axis": "height", "min": 0.12, "max": 0.2}]}}

	def test_static_support_and_scale_reach_opening_without_future_flow(self):
		from joymedia.services.planning.scene_contract import opening_instruction

		plan = self.plan()
		opening = opening_instruction(plan)
		self.assertIn("operator remains supported by the chair seat", opening)
		self.assertIn("0.12-0.2 times the height", opening)
		self.assertNotIn("originates", opening)
		self.assertIn("0.12-0.2 times the height", instruction(plan))
		self.assertEqual(read_contract(plan), read_contract({"scene_contract": read_contract(plan)}))

	def test_dimensions_are_invariant_temporal_claims(self):
		from joymedia.services.review.temporal import claims_for

		claims = claims_for(self.plan(), 3, "Move")
		scale = next(row for row in claims if row["id"] == "proportion.0")
		self.assertEqual(scale["mode"], "invariant")
		self.assertNotIn("window", scale)

	def test_malformed_dimensions_fail_before_admission(self):
		mutations = [
			{"subject": "missing"}, {"reference": "vessel"}, {"axis": "area"},
			{"axis": []}, {"min": True}, {"min": -1}, {"min": 0},
			{"max": math.inf}, {"min": math.nan}, {"min": 0.5, "max": 0.2},
			{"max": 101}, {"max": "0.2"}, {"min": 10 ** 400}, {"max": -(10 ** 400)},
		]
		for mutation in mutations:
			with self.subTest(mutation=mutation):
				plan = self.plan()
				plan["scene_contract"]["proportions"][0].update(mutation)
				with self.assertRaises(ValueError):
					read_contract(plan)
		for extra in [{"subject": "vessel", "reference": "actor", "axis": "height", "min": 0.1, "max": 0.3},
			{"subject": "actor", "reference": "vessel", "axis": "height", "min": 5, "max": 8}]:
			plan = self.plan()
			plan["scene_contract"]["proportions"].append(extra)
			with self.assertRaises(ValueError):
				read_contract(plan)

	def test_scale_edit_invalidates_approved_preview_signature(self):
		from joymedia.services.keyframes.stage import keyframe_signature

		shot = frappe._dict(image_prompt="Seated at work surface", generation_inputs=[], motion_plan_json=self.plan())
		before = keyframe_signature(shot)
		shot.motion_plan_json["scene_contract"]["proportions"][0]["max"] = 0.3
		self.assertNotEqual(before, keyframe_signature(shot))

	def test_frame_review_checks_support_and_scale_independently(self):
		from unittest.mock import patch

		from joymedia.services.review.consistency import frame_checks

		shot = frappe._dict(keyframe_artifact="ART", generation_inputs=[], motion_plan_json=self.plan())
		with patch("frappe.db.get_value", return_value="/private/frame.png"), patch("joymedia.services.keyframes.locations.shot_views", return_value=[]):
			checks = frame_checks(shot)
		self.assertEqual(len(checks), 2)
		self.assertTrue(all(row[2] is True and len(row) == 4 for row in checks))
		self.assertIn("chair seat", checks[0][1])
		self.assertIn("0.12-0.2", checks[1][1])

	def test_reference_draw_path_cannot_bypass_support_or_size_constraints(self):
		from unittest.mock import patch

		from joymedia.services.planning.prompts import compile_prompt_for_documents

		shot = frappe._dict(name="S", shot_number=1, image_prompt="The operator waits behind the table.",
			generation_prompt="The operator lifts the vessel.", setting_prompt="A workroom.",
			character_mode="Draw in scene", references=[{"reference_role": "Character", "asset_version": "REF"}],
			motion_plan_json=self.plan())
		project = frappe._dict(references=[{"asset_version": "REF", "label": "Operator"}])
		with patch("joymedia.services.keyframes.overlay.describe_colours", return_value=""):
			prompt = compile_prompt_for_documents(shot, project, prompt_source="image")
		self.assertEqual(prompt.count("Starting-frame staging:"), 1)
		self.assertIn("operator remains supported by the chair seat", prompt)
		self.assertIn("0.12-0.2 times the height", prompt)
		self.assertNotIn("liquid originates", prompt)
