"""Provider frame grids must not remove an authored action's resolved endpoint."""

import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase

from joymedia.services.editing.composer import _normalize_segment
from joymedia.services.runtime.media import probe_video


class TestTemporalFit(TestCase):
	def test_resampling_preserves_final_action_frame_and_exact_length(self):
		with tempfile.TemporaryDirectory() as folder:
			source = Path(folder) / "native.mp4"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-f",
					"lavfi",
					"-i",
					"color=red:s=64x64:r=24:d=2.333333334",
					"-f",
					"lavfi",
					"-i",
					"sine=frequency=440:duration=2.333333334",
					"-vf",
					"drawbox=x=0:y=0:w=iw:h=ih:color=blue:t=fill:enable='eq(n,55)'",
					"-frames:v",
					"56",
					"-c:v",
					"libx264",
					"-pix_fmt",
					"yuv420p",
					"-c:a",
					"aac",
					str(source),
				],
				check=True,
				capture_output=True,
			)
			self.assertEqual(56, probe_video(source)["frames"])
			for mode in ["trim", "preserve_endpoints"]:
				with self.subTest(mode=mode):
					output = Path(folder) / (mode + ".mp4")
					_normalize_segment(
						source,
						output,
						dict(width=64, height=64, fps=24, temporal_fit=mode),
						48,
						preserve_audio=True,
					)
					self.assertEqual(48, probe_video(output)["frames"])
					frames = subprocess.run(
						[
							"ffmpeg",
							"-v",
							"error",
							"-i",
							str(output),
							"-vf",
							"select='eq(n,0)+eq(n,47)',scale=1:1",
							"-fps_mode",
							"passthrough",
							"-pix_fmt",
							"rgb24",
							"-f",
							"rawvideo",
							"-",
						],
						check=True,
						capture_output=True,
					).stdout
					self.assertGreater(frames[0], 200)
					self.assertGreater(frames[5] if mode == "preserve_endpoints" else frames[3], 200)
					subprocess.run(
						["ffmpeg", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"],
						check=True,
						capture_output=True,
					)
