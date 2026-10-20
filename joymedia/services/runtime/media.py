"""Read source video geometry through the existing ffprobe metadata contract."""

import json
import subprocess


def probe_video(path):
	result = subprocess.run(
		["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(path)],
		check=True,
		capture_output=True,
		timeout=30,
	)
	streams = json.loads(result.stdout).get("streams", [])
	if len(streams) != 1:
		raise ValueError("A readable video stream is required.")
	stream = streams[0]
	from fractions import Fraction

	fps = float(Fraction(stream["avg_frame_rate"]))
	return {
		"width": int(stream["width"]),
		"height": int(stream["height"]),
		"fps": fps,
		"frames": int(stream.get("nb_frames") or round(float(stream["duration"]) * fps)),
	}
