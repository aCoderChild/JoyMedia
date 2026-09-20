"""Plan technical generation segments for a creative shot."""


MAX_SEGMENT_FRAMES = 124
CONTINUATION_OVERLAP_FRAMES = 1


def plan_generation_segments(
	planned_frame_count: int,
	max_segment_frames: int = MAX_SEGMENT_FRAMES,
):
	if planned_frame_count < 1:
		raise ValueError("planned_frame_count must be positive.")

	if max_segment_frames < 2:
		raise ValueError("max_segment_frames must be at least 2.")

	segments = []
	remaining_effective_frames = planned_frame_count

	first_frames = min(
		remaining_effective_frames,
		max_segment_frames,
	)

	segments.append(
		{
			"segment_index": 1,
			"segment_frame_count": first_frames,
		}
	)

	remaining_effective_frames -= first_frames
	effective_capacity = max_segment_frames - CONTINUATION_OVERLAP_FRAMES

	while remaining_effective_frames > 0:
		effective_frames = min(
			remaining_effective_frames,
			effective_capacity,
		)
		generated_frames = effective_frames + CONTINUATION_OVERLAP_FRAMES

		segments.append(
			{
				"segment_index": len(segments) + 1,
				"segment_frame_count": generated_frames,
			}
		)
		remaining_effective_frames -= effective_frames

	return segments
