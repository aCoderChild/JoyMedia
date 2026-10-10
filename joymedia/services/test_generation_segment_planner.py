from unittest import TestCase

from .generation_segment_planner import plan_generation_segments


class TestGenerationSegmentPlanner(TestCase):
	def test_plans_short_shot_as_one_segment(self):
		self.assertEqual(
			[{"segment_index": 1, "segment_start_frame": 0, "segment_frame_count": 120, "segment_effective_frames": 120, "overlap_frames": 0}],
			plan_generation_segments(120),
		)

	def test_plans_maximum_single_segment(self):
		self.assertEqual(
			[{"segment_index": 1, "segment_start_frame": 0, "segment_frame_count": 124, "segment_effective_frames": 124, "overlap_frames": 0}],
			plan_generation_segments(124),
		)

	def test_adds_overlap_to_continuation_segment(self):
		self.assertEqual(
			[
				{"segment_index": 1, "segment_start_frame": 0, "segment_frame_count": 124, "segment_effective_frames": 124, "overlap_frames": 0},
				{"segment_index": 2, "segment_start_frame": 124, "segment_frame_count": 2, "segment_effective_frames": 1, "overlap_frames": 1},
			],
			plan_generation_segments(125),
		)

	def test_plans_two_segments(self):
		self.assertEqual(
			[
				{"segment_index": 1, "segment_start_frame": 0, "segment_frame_count": 124, "segment_effective_frames": 124, "overlap_frames": 0},
				{"segment_index": 2, "segment_start_frame": 124, "segment_frame_count": 21, "segment_effective_frames": 20, "overlap_frames": 1},
			],
			plan_generation_segments(144),
		)

	def test_plans_segments_with_configured_overlap(self):
		self.assertEqual(
			[
				{"segment_index": 1, "segment_start_frame": 0, "segment_frame_count": 124, "segment_effective_frames": 124, "overlap_frames": 0},
				{"segment_index": 2, "segment_start_frame": 124, "segment_frame_count": 23, "segment_effective_frames": 1, "overlap_frames": 22},
			],
			plan_generation_segments(125, continuation_overlap_frames=22),
		)

		self.assertEqual(
			[
				{"segment_index": 1, "segment_start_frame": 0, "segment_frame_count": 124, "segment_effective_frames": 124, "overlap_frames": 0},
				{"segment_index": 2, "segment_start_frame": 124, "segment_frame_count": 80, "segment_effective_frames": 58, "overlap_frames": 22},
				{"segment_index": 3, "segment_start_frame": 182, "segment_frame_count": 80, "segment_effective_frames": 58, "overlap_frames": 22},
			],
			plan_generation_segments(240, continuation_overlap_frames=22),
		)

	def test_plans_long_shot_with_continuations(self):
		self.assertEqual(
			[
				{"segment_index": 1, "segment_start_frame": 0, "segment_frame_count": 124, "segment_effective_frames": 124, "overlap_frames": 0},
				{"segment_index": 2, "segment_start_frame": 124, "segment_frame_count": 104, "segment_effective_frames": 103, "overlap_frames": 1},
				{"segment_index": 3, "segment_start_frame": 227, "segment_frame_count": 104, "segment_effective_frames": 103, "overlap_frames": 1},
				{"segment_index": 4, "segment_start_frame": 330, "segment_frame_count": 103, "segment_effective_frames": 102, "overlap_frames": 1},
			],
			plan_generation_segments(432),
		)

	def test_rejects_non_positive_planned_frame_count(self):
		with self.assertRaisesRegex(ValueError, "planned_frame_count must be positive"):
			plan_generation_segments(0)

	def test_rejects_segment_limit_below_two_frames(self):
		with self.assertRaisesRegex(ValueError, "max_segment_frames must be at least 2"):
			plan_generation_segments(10, max_segment_frames=1)

	def test_continuations_can_add_a_full_segment_of_new_footage(self):
		# A 10 s take is one first segment and one continuation, not two slivers.
		segments = plan_generation_segments(240, 124, 22, continuation_new_frames=124)
		self.assertEqual([124, 80, 80], [s["segment_frame_count"] for s in segments])
		self.assertEqual(240, sum(s["segment_effective_frames"] for s in segments))
		self.assertTrue(all(s["segment_frame_count"] <= 124 for s in segments[1:]))
