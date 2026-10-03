import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from joymedia.services import finishing
from joymedia.services.video_composer import _validate_normalized_video


def _fake_comfyui_chunk(chunk_path, kept):
	"""Stand-in for ESRGAN x2 + RIFE x5 + every 2nd frame + overlap trim: same frames and size."""
	output = Path(chunk_path).with_suffix(".fake.mp4")
	subprocess.run(
		["ffmpeg", "-v", "error", "-y", "-i", str(chunk_path), "-vf",
		 f"scale=iw*2:ih*2,fps=60,tpad=stop_mode=clone:stop_duration=1,trim=end_frame={kept}",
		 "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)],
		check=True,
	)
	return output.read_bytes()


class TestFinishing(FrappeTestCase):
	def test_studio_profiles(self):
		delivery = {"width": 1920, "height": 1080, "fps": 24.0}
		self.assertEqual({"width": 2560, "height": 1440, "fps": 60.0}, finishing.studio_profile(delivery))
		self.assertEqual({"width": 1280, "height": 720, "fps": 24.0}, finishing.render_profile(delivery))
		self.assertEqual({"width": 1440, "height": 2560, "fps": 60.0}, finishing.studio_profile({"width": 1080, "height": 1920, "fps": 24.0}))
		self.assertEqual(1800, finishing.finished_frame_count(720, 24))
		self.assertEqual(60, finishing.finished_chunk_frames(25, has_overlap=True))
		self.assertEqual(58, finishing.finished_chunk_frames(24, has_overlap=False))

	def test_chunks_join_into_an_exact_60fps_film(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-finish-test-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "finished.mp4"
			# 58 frames: two full chunks with overlap and a short last chunk.
			subprocess.run(
				["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=2.4167",
				 "-frames:v", "58", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
				check=True,
			)

			with patch.object(finishing, "_finish_chunk", side_effect=_fake_comfyui_chunk) as finish_chunk:
				finishing.finish_video(source, output, 58, 24.0, temp_path)

			self.assertEqual(3, finish_chunk.call_count)
			# Each chunk but the last carries the next chunk's first frame.
			self.assertEqual([25, 25, 10], [finishing._frame_count(call.args[0]) for call in finish_chunk.call_args_list])
			_validate_normalized_video(
				output, {"width": 320, "height": 180, "fps": 60.0}, expected_frames=finishing.finished_frame_count(58, 24)
			)
