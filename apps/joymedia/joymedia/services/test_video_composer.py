import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.video_composer import _mix_audio, _validate_shots


class TestVideoComposer(FrappeTestCase):
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
