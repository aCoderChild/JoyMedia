from unittest import TestCase

from .generation_segment_planner import plan_generation_segments


class TestGenerationSegmentPlanner(TestCase):
	def test_plans_short_shot_as_one_segment(self):
		self.assertEqual(
			[{"segment_index": 1, "segment_frame_count": 120}],
			plan_generation_segments(120),
		)

	def test_plans_maximum_single_segment(self):
		self.assertEqual(
			[{"segment_index": 1, "segment_frame_count": 124}],
			plan_generation_segments(124),
		)

	def test_adds_overlap_to_continuation_segment(self):
		self.assertEqual(
			[
				{"segment_index": 1, "segment_frame_count": 124},
				{"segment_index": 2, "segment_frame_count": 2},
			],
			plan_generation_segments(125),
		)

	def test_plans_two_segments(self):
		self.assertEqual(
			[
				{"segment_index": 1, "segment_frame_count": 124},
				{"segment_index": 2, "segment_frame_count": 21},
			],
			plan_generation_segments(144),
		)

	def test_plans_long_shot_with_continuations(self):
		self.assertEqual(
			[
				{"segment_index": 1, "segment_frame_count": 124},
				{"segment_index": 2, "segment_frame_count": 124},
				{"segment_index": 3, "segment_frame_count": 124},
				{"segment_index": 4, "segment_frame_count": 63},
			],
			plan_generation_segments(432),
		)

	def test_rejects_non_positive_planned_frame_count(self):
		with self.assertRaisesRegex(ValueError, "planned_frame_count must be positive"):
			plan_generation_segments(0)

	def test_rejects_segment_limit_below_two_frames(self):
		with self.assertRaisesRegex(ValueError, "max_segment_frames must be at least 2"):
			plan_generation_segments(10, max_segment_frames=1)
