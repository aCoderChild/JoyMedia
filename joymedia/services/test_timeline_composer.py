import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.timeline_composer import _normalize_clip, _render_sequence
from joymedia.services.video_composer import _get_video_duration, _validate_normalized_video


class TestTimelineComposer(FrappeTestCase):
	def test_normalize_clip_extracts_frame_exact_source_range(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-timeline-trim-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "clip.mp4"
			_make_video(source, 2)
			profile = {"width": 320, "height": 240, "fps": 24.0}

			_normalize_clip(source, output, profile, source_in_frame=12, source_out_frame=36)

			_validate_normalized_video(output, profile, expected_frames=24)
			self.assertAlmostEqual(_get_video_duration(output), 1.0, delta=0.05)

	def test_render_sequence_honors_dissolve_overlap(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-timeline-xfade-") as temp_dir:
			temp_path = Path(temp_dir)
			first = temp_path / "first.mp4"
			second = temp_path / "second.mp4"
			output = temp_path / "master.mp4"
			_make_video(first, 1, color="red")
			_make_video(second, 1, color="blue")
			profile = {"width": 320, "height": 240, "fps": 24.0}
			clips = [
				frappe._dict(name="A", transition_to_next="Dissolve"),
				frappe._dict(name="B", transition_to_next="Cut"),
			]

			_render_sequence(
				[first, second],
				clips,
				[24, 24],
				[6, 0],
				output,
				profile,
			)

			_validate_normalized_video(output, profile, expected_frames=42)
			self.assertAlmostEqual(_get_video_duration(output), 42 / 24, delta=0.06)

	def test_render_sequence_honors_persisted_video_position(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-timeline-position-test-") as temp_dir:
			temp_path = Path(temp_dir)
			first = temp_path / "first.mp4"
			second = temp_path / "second.mp4"
			output = temp_path / "master.mp4"
			_make_video(first, 1, color="red")
			_make_video(second, 1, color="blue")
			profile = {"width": 320, "height": 240, "fps": 24.0}
			clips = [
				frappe._dict(name="A", timeline_start_frame=0, transition_to_next="Cut"),
				frappe._dict(name="B", timeline_start_frame=48, transition_to_next="Cut"),
			]

			_render_sequence(
				[first, second],
				clips,
				[24, 24],
				[0, 0],
				output,
				profile,
				positioned=True,
			)

			_validate_normalized_video(output, profile, expected_frames=72)
			self.assertAlmostEqual(_get_video_duration(output), 72 / 24, delta=0.06)


def _make_video(path, seconds, color="black"):
	subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-y",
			"-f",
			"lavfi",
			"-i",
			f"color=c={color}:s=320x240:r=24:d={seconds}",
			"-an",
			"-c:v",
			"libx264",
			"-profile:v",
			"high",
			"-pix_fmt",
			"yuv420p",
			str(path),
		],
		check=True,
	)
