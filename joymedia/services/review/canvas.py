"""Observe persistent border candidates with FFmpeg's existing cropdetect filter.

Upstream: FFmpeg/FFmpeg n5.1.9, libavfilter/vf_cropdetect.c (LGPL-2.1-or-later).
Invoke the installed filter; do not reimplement its pixel detector or crop media.
Dark artistic backgrounds can resemble borders, so findings require review.
"""

import re
import subprocess


def inspect_active_canvas(path, width, height):
	try:
		result = subprocess.run(
			[
				"ffmpeg",
				"-nostdin",
				"-hide_banner",
				"-nostats",
				"-i",
				str(path),
				"-an",
				"-sn",
				"-dn",
				"-vf",
				"cropdetect",
				"-f",
				"null",
				"-",
			],
			check=True,
			capture_output=True,
			text=True,
			timeout=60,
		)
	except (OSError, subprocess.SubprocessError):
		return {"status": "unavailable", "reason": "FFmpeg could not inspect the active picture."}
	# Unrounded pixel extents avoid cropdetect's encoding-alignment rounding.
	# Its default reset=0 accumulates the largest visible area across the clip.
	rows = re.findall(r"x1:(\d+) x2:(\d+) y1:(\d+) y2:(\d+)", result.stderr)
	if not rows:
		return {"status": "unavailable", "reason": "FFmpeg returned no active-picture observation."}
	x1, x2, y1, y2 = map(int, rows[-1])
	if not (0 <= x1 <= x2 < width and 0 <= y1 <= y2 < height):
		return {"status": "unavailable", "reason": "No valid non-black picture rectangle was detected."}
	margins = {"left": x1, "right": width - x2 - 1, "top": y1, "bottom": height - y2 - 1}
	return {
		"status": "border_candidate" if any(margins.values()) else "full_frame",
		"detector": "ffmpeg.cropdetect",
		"bounds": [x1, y1, x2 + 1, y2 + 1],
		"canvas": [width, height],
		"margins": margins,
		"observations": len(rows),
		"limitations": "Black-border candidates only; dark intentional scenery may require review. No media was cropped.",
	}
