from unittest import TestCase

import frappe
from hypothesis import given, settings
from hypothesis import strategies as st

from joymedia.services.generation.segments import plan_generation_segments
from joymedia.services.workflows.capabilities import capacity, controls, require_controls, validate_contract


class TestCapabilities(TestCase):
	def test_capacity_belongs_to_the_workflow_not_a_model_name(self):
		self.assertEqual(capacity({"frame_count": 362}), 362)
		self.assertEqual(
			capacity({"frame_count": 124, "execution_spec": '{"limits":{"max_frames":241}}'}), 241
		)
		for invalid in [True, 0, -1, 2.5, float("nan"), float("inf"), "124"]:
			with self.subTest(invalid=invalid), self.assertRaises(ValueError):
				capacity({"frame_count": invalid})

	def test_controls_are_explicit_and_do_not_certify_identity(self):
		workflow = {"execution_spec": {"capabilities": ["reference_image", "mask", "pose"]}}
		self.assertEqual(controls(workflow), {"reference_image", "mask", "pose"})
		with self.assertRaisesRegex(ValueError, "reference_video"):
			require_controls(workflow, {"reference_video"})
		for spec in [{"capabilities": "mask"}, {"limits": []}, {"limits": {"max_frames": 0}}]:
			with self.assertRaises(ValueError):
				validate_contract(spec)

	def test_resource_budget_rejects_extreme_requests_before_allocation(self):
		with self.assertRaisesRegex(ValueError, "budget"):
			plan_generation_segments(10**12, 124)

	@settings(max_examples=500, deadline=None, derandomize=True)
	@given(
		total=st.integers(1, 20000),
		initial=st.integers(2, 600),
		later=st.integers(2, 600),
		offset=st.integers(0, 600),
	)
	def test_random_workflow_capacities_preserve_timing(self, total, initial, later, offset):
		overlap = offset % min(initial, later)
		# This property checks timing across many fictional model capacities,
		# including workflows much larger and smaller than the original provider.
		try:
			segments = plan_generation_segments(
				total, initial, overlap, continuation_max_segment_frames=later
			)
		except ValueError as exc:
			self.assertIn("budget", str(exc))
			return
		self.assertEqual(sum(s["segment_effective_frames"] for s in segments), total)
		self.assertLessEqual(segments[0]["segment_frame_count"], initial)
		position = 0
		for index, segment in enumerate(segments):
			self.assertEqual(segment["segment_start_frame"], position)
			self.assertGreater(segment["segment_effective_frames"], 0)
			self.assertEqual(
				segment["segment_frame_count"] - segment["overlap_frames"],
				segment["segment_effective_frames"],
			)
			if index:
				self.assertLessEqual(segment["segment_frame_count"], later)
			position += segment["segment_effective_frames"]
