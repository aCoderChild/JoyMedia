import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.timeline_composer import (
	_apply_ending,
	_get_generated_audio_sources,
	_normalize_clip,
	_render_sequence,
)
from joymedia.services.video_composer import _get_video_duration, _validate_normalized_video


class TestTimelineComposer(FrappeTestCase):
	def test_generated_audio_sources_preserve_video_audio_timing(self):
		clip = frappe._dict(
			name="CLIP-1",
			timeline_start_frame=12,
			source_asset_version="ASTV-1",
			source_in_frame=24,
			source_out_frame=72,
		)

		with (
			patch("joymedia.services.timeline_composer._asset_version_path", return_value=Path("video.mp4")),
			patch("joymedia.services.timeline_composer._has_audio_stream", return_value=True),
		):
			sources = _get_generated_audio_sources(
				[clip], [48], 4.0, 24.0, positioned=True, transition_frames=[0]
			)

		self.assertEqual(
			{
				"path": Path("video.mp4"),
				"start_seconds": 0.5,
				"source_start_seconds": 1.0,
				"duration_seconds": 2.0,
				"gain_db": 0,
				"fade_in_seconds": 0,
				"fade_out_seconds": 0,
				"duck_others": False,
				"loop": False,
			},
			sources[0],
		)

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

	def test_ending_preserves_picture_before_fade(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-ending-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "ended.mp4"
			_make_video(source, 6, color="white")
			profile = {"width": 320, "height": 240, "fps": 24.0}

			_apply_ending(source, output, profile, temp_path)

			_validate_normalized_video(output, profile, expected_frames=144)
			before, after = _mean_luma(output, 2.0), _mean_luma(output, 4.8)
			self.assertGreater(before, 200)
			self.assertGreater(after, 200)

	def test_every_film_fades_to_black_at_the_end(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-ending-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "ended.mp4"
			_make_video(source, 4, color="white")
			profile = {"width": 320, "height": 240, "fps": 24.0}

			_apply_ending(source, output, profile, temp_path)

			_validate_normalized_video(output, profile, expected_frames=96)
			self.assertGreater(_mean_luma(output, 2.0), 200)
			self.assertLess(_mean_luma(output, 3.92), 40)

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


def _mean_luma(path, seconds):
	output = subprocess.run(
		["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(path), "-frames:v", "1",
		 "-vf", "format=gray,crop=iw:ih/3,scale=1:1:flags=area", "-f", "rawvideo", "-"],
		capture_output=True, check=True,
	).stdout
	return output[0]


class TestSceneCaptions(FrappeTestCase):
	def test_caption_shows_in_the_lower_third_during_its_scene(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-caption-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "captioned.mp4"
			_make_video(source, 6, color="black")
			profile = {"width": 320, "height": 240, "fps": 24.0}

			_apply_ending(source, output, profile, temp_path, [(0.0, 4.0, "Không gian sống xanh")])

			def lower_third(seconds):
				pixels = subprocess.run(
					["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(output), "-frames:v", "1",
					 "-vf", "format=gray,crop=iw:ih/6:0:ih*0.74", "-f", "rawvideo", "-"],
					capture_output=True, check=True,
				).stdout
				return max(pixels)

			self.assertLess(lower_third(0.1), 40)
			self.assertGreater(lower_third(2.0), 150)
			self.assertLess(lower_third(5.0), 40)
