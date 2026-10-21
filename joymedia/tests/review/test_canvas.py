import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase, skipUnless

from joymedia.services.review.canvas import inspect_active_canvas


@skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for native media screening")
class TestActiveCanvas(TestCase):
	def render(self, root, source):
		path = Path(root) / "sample.mp4"
		subprocess.run(
			["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-c:v", "libx264", str(path)],
			check=True,
			capture_output=True,
			timeout=30,
		)
		return path

	def test_native_detector_distinguishes_borders_from_full_picture_without_cropping(self):
		with tempfile.TemporaryDirectory() as root:
			for source, expected in [
				("color=white:s=64x96:r=24:d=0.3", "full_frame"),
				("color=white:s=64x32:r=24:d=0.3,pad=64:96:0:32:black", "border_candidate"),
			]:
				with self.subTest(expected=expected):
					path = self.render(root, source)
					before = path.read_bytes()
					report = inspect_active_canvas(path, 64, 96)
					self.assertEqual(expected, report["status"])
					self.assertEqual(before, path.read_bytes())
					if expected == "border_candidate":
						self.assertEqual({"top": 32, "bottom": 32, "left": 0, "right": 0}, report["margins"])

	def test_unreadable_media_is_unknown_instead_of_accepted(self):
		with tempfile.TemporaryDirectory() as root:
			self.assertEqual(
				"unavailable", inspect_active_canvas(Path(root) / "missing.mp4", 64, 96)["status"]
			)
