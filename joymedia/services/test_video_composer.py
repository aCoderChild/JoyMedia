import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.video_composer import (
	_get_video_duration,
	_mix_audio,
	_normalize_shot,
	_validate_normalized_video,
	_validate_shots,
	_get_delivery_profile,
)


class TestVideoComposer(FrappeTestCase):
	def test_delivery_profile_uses_generation_run_snapshot_dimensions(self):
		project = frappe._dict(delivery_width=1080, delivery_height=1920, workflow="LIVE-WORKFLOW")
		run = frappe._dict(
		name="RUN-00001",
		project_snapshot_json='{"delivery_width": 1920, "delivery_height": 1080, "workflow": "SNAPSHOT-WORKFLOW"}',
		workflow="SNAPSHOT-WORKFLOW",
		)
		workflow = frappe._dict(output_fps=24)
		with patch("joymedia.services.video_composer.frappe.get_doc", side_effect=[run, workflow]):
			profile = _get_delivery_profile(project, "RUN-00001")
		self.assertEqual({"width": 1920, "height": 1080, "fps": 24.0}, profile)

	def test_composition_requires_a_selected_output_for_every_shot(self):
		with self.assertRaises(frappe.ValidationError):
			_validate_shots(
				[
					frappe._dict(
						name="SHOT-00001",
						shot_number=1,
						selected_output_asset_version=None,
					)
				],
				"SPEC-00001",
			)

	def test_normalize_shot_trims_to_editor_frame_count(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-trim-test-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "trimmed.mp4"
			_run_ffmpeg(
				"-f",
				"lavfi",
				"-i",
				"testsrc=size=320x240:rate=24:duration=2",
				"-an",
				"-c:v",
				"libx264",
				"-pix_fmt",
				"yuv420p",
				str(source),
			)
			profile = {"width": 320, "height": 240, "fps": 24.0}
			_normalize_shot(source, output, profile, planned_frames=24)
			_validate_normalized_video(output, profile, expected_frames=24)
			self.assertAlmostEqual(_get_video_duration(output), 1.0, delta=0.05)

	def test_normalize_shot_extends_short_source_by_holding_last_frame(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-extend-test-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "extended.mp4"
			_run_ffmpeg(
				"-f",
				"lavfi",
				"-i",
				"testsrc=size=320x240:rate=24:duration=1",
				"-an",
				"-c:v",
				"libx264",
				"-pix_fmt",
				"yuv420p",
				str(source),
			)
			profile = {"width": 320, "height": 240, "fps": 24.0}
			_normalize_shot(source, output, profile, planned_frames=48)
			_validate_normalized_video(output, profile, expected_frames=48)
			self.assertAlmostEqual(_get_video_duration(output), 2.0, delta=0.05)

	def test_normalize_segment_clamps_audio_to_exact_target_duration(self):
		from joymedia.services.video_composer import _normalize_segment

		with tempfile.TemporaryDirectory(prefix="joymedia-cumulative-audio-test-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "normalized.mp4"
			_run_ffmpeg(
				"-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=2",
				"-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
				"-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
				"-c:a", "aac", str(source),
			)
			profile = {"width": 320, "height": 240, "fps": 24.0}
			_normalize_segment(source, output, profile, generated_frames=24, drop_first=False, preserve_audio=True)
			_validate_normalized_video(output, profile, expected_frames=24)
			self.assertAlmostEqual(_get_video_duration(output), 1.0, delta=0.05)
			audio_duration = float(
				json.loads(
					subprocess.run(
						[
							"ffprobe", "-v", "error", "-select_streams", "a:0",
							"-show_entries", "stream=duration", "-of", "json", str(output),
						], capture_output=True, text=True, check=True,
					).stdout
				)["streams"][0]["duration"]
			)
			self.assertAlmostEqual(audio_duration, 1.0, delta=0.05)

	def test_mix_audio_supports_timed_gain_fades_and_ducking(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-audio-test-") as temp_dir:
			temp_path = Path(temp_dir)
			silent_master = temp_path / "silent.mp4"
			bgm = temp_path / "bgm.wav"
			voiceover = temp_path / "voiceover.wav"
			delivery = temp_path / "delivery.mp4"
			_run_ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x240:r=24:d=2", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent_master))
			_run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-c:a", "pcm_s16le", str(bgm))
			_run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=0.8", "-c:a", "pcm_s16le", str(voiceover))

			_mix_audio(
				silent_master,
				[
					{
						"path": bgm,
						"start_seconds": 0,
						"duration_seconds": 2,
						"gain_db": -8,
						"fade_in_seconds": 0.1,
						"fade_out_seconds": 0.1,
						"duck_others": False,
						"loop": True,
					},
					{
						"path": voiceover,
						"start_seconds": 0.5,
						"duration_seconds": 1,
						"gain_db": 0,
						"fade_in_seconds": 0.05,
						"fade_out_seconds": 0.05,
						"duck_others": True,
						"loop": False,
					},
				],
				delivery,
			)

			stream_types = subprocess.run(
				[
					"ffprobe",
					"-v",
					"error",
					"-show_entries",
					"stream=codec_type",
					"-of",
					"csv=p=0",
					str(delivery),
				],
				capture_output=True,
				text=True,
				check=True,
			).stdout.splitlines()
			self.assertEqual(stream_types, ["video", "audio"])


def _run_ffmpeg(*arguments):
	subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], check=True)
