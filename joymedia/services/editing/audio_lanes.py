"""Place independent audio clips on reusable timeline tracks.

Track zero is reserved for audio linked to the source video. Independent clips
can share a track when their frame ranges do not overlap and their roles match.
"""


def choose_audio_track(clips, role, start_frame, duration_frames):
	"""Return an existing compatible track or the next free positive index."""
	end_frame = start_frame + duration_frames
	compatible = sorted(
		{
			int(clip.track_index or 0)
			for clip in clips
			if clip.audio_role == role and int(clip.track_index or 0) > 0
		}
	)
	for index in compatible:
		if all(
			end_frame <= int(clip.timeline_start_frame or 0)
			or start_frame
			>= int(clip.timeline_start_frame or 0)
			+ max(1, int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0))
			for clip in clips
			if int(clip.track_index or 0) == index
		):
			return index
	return max([int(clip.track_index or 0) for clip in clips] or [0]) + 1
