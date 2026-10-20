"""A visible touch cannot substitute for a state-changing physical action."""

import copy
from unittest import TestCase

from joymedia.services.scene.contract import instruction, opening_claims, read_contract
from joymedia.services.scene.evidence import (
	SequenceCheck,
	batches,
	claims_for,
	evaluate,
	merge_observations,
	question,
	sample_times,
)

PLAN = {
	"scene_contract": {
		"version": 1,
		"entities": [{"id": "material", "label": "the affected material"}],
		"relations": [],
		"events": [
			{"id": "work", "description": "The tool changes the material", "start": 0, "end": 2, "after": []}
		],
		"transitions": [
			{
				"event": "work",
				"before": "The initial material remains visible",
				"during": "The tool maintains contact while moving across the material",
				"after": "The affected region visibly changes along the contact path",
				"forbidden": "The tool lifts while the affected region remains unchanged",
			}
		],
	}
}


class TestPhysicalTransitions(TestCase):
	def check(self):
		claim = next(
			row
			for row in claims_for(PLAN, 2, "Work the material")
			if row.get("evidence_kind") == "transition"
		)
		return SequenceCheck(
			[],
			[{"index": i, "time": t} for i, t in enumerate([0, 0.5, 1, 1.5, 47 / 24])],
			[claim],
			{"required_claim_ids": [claim["id"]]},
		)

	def answer(self, **overrides):
		return {
			"observations": [
				{
					"id": "transition.work",
					"verdict": "supported",
					"frames": [0, 2, 4],
					"phase_frames": {"before": 0, "during": 2, "after": 4},
					"reason": "Contact drives a visible material change",
					**overrides,
				}
			]
		}

	def test_touch_or_lift_without_result_cannot_pass(self):
		check = self.check()
		for phases in [
			None,
			{},
			{"before": 0, "during": 2, "after": 2},
			{"before": 0, "during": 1, "after": 2},
			{"before": True, "during": 2, "after": 4},
		]:
			with self.subTest(phases=phases):
				self.assertEqual("Needs Review", evaluate(check, self.answer(phase_frames=phases))["status"])
		self.assertEqual("Passed", evaluate(check, self.answer())["status"])
		self.assertEqual(
			"Needs Review",
			evaluate(
				check, self.answer(verdict="violated", reason="Material remains unchanged after contact")
			)["status"],
		)
		self.assertEqual(
			"Needs Review",
			evaluate(check, self.answer(verdict="uncertain", frames=[], reason="Result is hidden"))["status"],
		)

	def test_phase_witness_survives_merge_and_violation_dominates(self):
		check = self.check()
		good = evaluate(check, self.answer())
		self.assertEqual("Passed", merge_observations(check, [good])["status"])
		bad = evaluate(check, self.answer(verdict="violated"))
		self.assertEqual("Needs Review", merge_observations(check, [good, bad])["status"])

	def test_sampler_and_batch_keep_distinct_contact_and_result_frames(self):
		times = sample_times(2, 24, PLAN, frame_count=48)
		self.assertTrue({0, 1, 47 / 24}.issubset(times))
		check = self.check()
		indices, claims = next(batches(check))
		self.assertEqual((0, 2, 4), indices)
		self.assertEqual("transition.work", claims[0]["id"])
		self.assertIn("Does the video follow the physical rule:", question(check))
		self.assertNotIn("<|video|>", question(check))

	def test_invalid_or_unobservable_transition_is_rejected(self):
		for change in [{"event": "invented"}, {"before": ""}, {"extra": True}]:
			plan = copy.deepcopy(PLAN)
			plan["scene_contract"]["transitions"][0].update(change)
			with self.subTest(change=change), self.assertRaises(ValueError):
				read_contract(plan, 2)
		short = copy.deepcopy(PLAN)
		short["scene_contract"]["events"][0]["end"] = 0.01
		with self.assertRaises(ValueError):
			sample_times(2, 24, short)

	def test_provider_neutral_prompt_clips_state_without_restarting(self):
		full = instruction(PLAN, 2)
		self.assertIn("before contact", full)
		self.assertIn("visible result", full)
		self.assertIn("Do not show", full)
		continuation = instruction(PLAN, 2, start=1, end=2)
		self.assertNotIn("before contact", continuation)
		self.assertIn("visible result", continuation)
		first = instruction(PLAN, 2, start=0, end=1)
		self.assertNotIn("visible result", first)
		self.assertIn("The initial material remains visible", opening_claims(PLAN, 2))
		self.assertNotIn(
			"The affected region visibly changes along the contact path", opening_claims(PLAN, 2)
		)
