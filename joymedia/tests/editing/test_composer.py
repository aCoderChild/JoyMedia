import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.editing.composer import (
	_get_delivery_profile,
	_get_video_duration,
	_mix_audio,
	_validate_normalized_video,
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
		with patch("joymedia.services.editing.composer.frappe.get_doc", side_effect=[run, workflow]):
			profile = _get_delivery_profile(project, "RUN-00001")
		self.assertEqual({"width": 1920, "height": 1080, "fps": 24.0}, profile)

	def test_normalize_segment_clamps_audio_to_exact_target_duration(self):
		from joymedia.services.editing.composer import _normalize_segment

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


class TestSegmentAssemblyWithAudio(FrappeTestCase):
	def _clip_with_audio(self, path, frames):
		seconds = frames / 24
		_run_ffmpeg(
			"-f", "lavfi", "-i", f"color=c=white:s=320x240:r=24:d={seconds}",
			"-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds + 0.05}",
			"-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-r", "24", str(path),
		)

	def test_joined_segments_with_audio_keep_the_exact_frame_count(self):
		from joymedia.services.editing.composer import (
			_concatenate_normalized_shots,
			_validate_normalized_video,
		)

		profile = {"width": 320, "height": 240, "fps": 24.0}
		with tempfile.TemporaryDirectory(prefix="joymedia-concat-") as temp_dir:
			temp = Path(temp_dir)
			first, second = temp / "a.mp4", temp / "b.mp4"
			self._clip_with_audio(first, 124)
			self._clip_with_audio(second, 44)
			joined = temp / "joined.mp4"
			_concatenate_normalized_shots([first, second], joined, profile, expected_frames=168)

			_validate_normalized_video(joined, profile, expected_frames=168)


class TestSceneLoudnessLeveling(FrappeTestCase):
	def _tone(self, path, volume_db):
		_run_ffmpeg(
			"-f", "lavfi", "-i", f"sine=frequency=300:duration=3,volume={volume_db}dB", "-c:a", "pcm_s16le", str(path),
		)

	def _mean_db(self, path, start, end):
		result = subprocess.run(
			["ffmpeg", "-v", "info", "-ss", str(start), "-to", str(end), "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"],
			capture_output=True, text=True,
		)
		return float(result.stderr.split("mean_volume:")[1].split("dB")[0])

	def _mix(self, temp, normalize):
		quiet, loud = temp / "quiet.wav", temp / "loud.wav"
		self._tone(quiet, -35)
		self._tone(loud, -8)
		master = temp / "master.mp4"
		_run_ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=320x240:r=24:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(master))
		sources = [
			{"path": path, "start_seconds": start, "duration_seconds": 3, "gain_db": 0, "fade_in_seconds": 0,
			 "fade_out_seconds": 0, "duck_others": False, "loop": False, "normalize_loudness": normalize}
			for path, start in ((quiet, 0), (loud, 3))
		]
		out = temp / ("leveled.mp4" if normalize else "raw.mp4")
		_mix_audio(master, sources, out)
		return out

	def test_scenes_are_brought_to_a_common_loudness(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-level-") as temp_dir:
			temp = Path(temp_dir)
			raw, leveled = self._mix(temp, False), self._mix(temp, True)
			raw_gap = abs(self._mean_db(raw, 0.2, 2.8) - self._mean_db(raw, 3.2, 5.8))
			leveled_gap = abs(self._mean_db(leveled, 0.2, 2.8) - self._mean_db(leveled, 3.2, 5.8))

			self.assertGreater(raw_gap, 20)
			self.assertLess(leveled_gap, 4)


class TestSilentScenesAreNotAmplified(FrappeTestCase):
	def test_silence_is_not_audible_and_a_quiet_tone_is(self):
		from joymedia.services.editing.composer import _is_audible

		with tempfile.TemporaryDirectory(prefix="joymedia-silent-") as temp_dir:
			temp = Path(temp_dir)
			silent, quiet = temp / "silent.wav", temp / "quiet.wav"
			_run_ffmpeg("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "2", str(silent))
			_run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=300:duration=2,volume=-12dB", "-c:a", "pcm_s16le", str(quiet))
			self.assertFalse(_is_audible(silent, 2))
			self.assertTrue(_is_audible(quiet, 2))


class TestSoundEffectsOnlyMode(FrappeTestCase):
	def _sources(self, mode):
		from joymedia.services.editing.composer import _get_audio_sources

		clips = [
			frappe._dict(name="SRC", audio_role="Source", timeline_start_frame=0, source_in_frame=0, source_out_frame=48,
				fade_in_frames=0, fade_out_frames=0, gain_db=0, duck_others=0),
			frappe._dict(name="FX", audio_role="SFX", timeline_start_frame=0, source_in_frame=0, source_out_frame=48,
				fade_in_frames=0, fade_out_frames=0, gain_db=0, duck_others=0),
		]
		with patch("joymedia.services.editing.composer._get_timeline_audio_path", return_value="/x.wav"), patch(
			"joymedia.services.editing.composer._is_audible", return_value=True
		):
			return _get_audio_sources(frappe._dict(soundtrack_mode=mode), 10, clips, 24)

	def test_full_soundtrack_keeps_the_video_models_audio(self):
		self.assertEqual(2, len(self._sources("Full soundtrack")))

	def test_sound_effects_only_keeps_the_video_models_prompted_audio(self):
		self.assertEqual(2, len(self._sources("Sound effects only")))

	def test_separate_effects_layer_drops_scene_audio_and_keeps_the_effects(self):
		sources = self._sources("Separate effects layer")
		self.assertEqual(1, len(sources))
		self.assertFalse(sources[0]["normalize_loudness"])


class TestAudioSpansTheWholeFilm(FrappeTestCase):
	def test_a_short_effect_is_padded_so_the_audio_track_is_as_long_as_the_video(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-pad-") as temp_dir:
			temp = Path(temp_dir)
			effect, master, out = temp / "fx.wav", temp / "master.mp4", temp / "out.mp4"
			_run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=300:duration=1", "-c:a", "pcm_s16le", str(effect))
			_run_ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=320x240:r=24:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(master))
			source = {"path": effect, "start_seconds": 0, "duration_seconds": 1, "gain_db": 0, "fade_in_seconds": 0,
				"fade_out_seconds": 0, "duck_others": False, "loop": False}
			_mix_audio(master, [source], out, ending=(5.0, 1.0))
			audio = float(subprocess.run(
				["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "csv=p=0", str(out)],
				capture_output=True, text=True,
			).stdout.strip())
			self.assertAlmostEqual(6.0, audio, delta=0.1)
