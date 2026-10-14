"""A rough screen for whether a clip's sound is sound effects rather than music or a voice.

The video model makes its soundtrack together with the picture and cannot be told to leave music or voice out.
Effects such as rustling and tearing are noise-like (a flat spectrum); music and voices are tonal (spectrum
concentrated at a pitch and its harmonics). The mean spectral flatness of the audible parts separates them well
on rendered clips, but it is a screen, not proof: a clip near the line should be listened to.
"""

import re
import subprocess


# Measured on rendered clips: effects-like clips scored 0.43 to 0.59, music-like ones 0.09 to 0.28. Scores from
# the minimum to BORDERLINE_MAX are accepted but should be listened to.



def effects_score(path):
	"""Mean spectral flatness (0 tonal ... 1 noise) of the audible parts of a file's audio, None when silent."""
	output = subprocess.run(
		[
			"ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-af",
			"silenceremove=stop_periods=-1:stop_threshold=-45dB:stop_duration=0.05,aspectralstats=win_size=1024,"
			"ametadata=print:key=lavfi.aspectralstats.1.flatness:file=-",
			"-f", "null", "-",
		],
		capture_output=True, text=True,
	).stdout
	# Digital silence reports a flatness of exactly 0; it carries no information about the sound.
	values = [value for value in (float(v) for v in re.findall(r"flatness=([0-9.eE+-]+)", output)) if value > 0]
	return round(sum(values) / len(values), 3) if values else None

