import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.editing.composer import _get_video_duration, _validate_normalized_video
from joymedia.services.editing.export import (
	_apply_ending,
	_assert_timeline_unchanged,
	_caption_cues,
	_normalize_clip,
	_render_positioned_sequence,
	_render_sequence,
)


class TestTimelineComposer(FrappeTestCase):
	def test_cut_only_sequence_joins_six_normalized_clips_without_filter_graph(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-timeline-cuts-") as temp_dir:
			root = Path(temp_dir)
			paths = [root / f"clip-{index}.mp4" for index in range(6)]
			for path in paths:
				_make_video(path, 1)
			output = root / "master.mp4"
			clips = [frappe._dict(name=str(index), transition_to_next="Cut") for index in range(6)]
			profile = {"width": 320, "height": 240, "fps": 24.0}
			_render_sequence(paths, clips, [24] * 6, [0] * 6, output, profile)
			_validate_normalized_video(output, profile, expected_frames=144)

	def test_changed_timeline_is_not_promoted_by_an_old_export(self):
		with patch("joymedia.services.editing.post_production.timeline_signature", return_value="newer-edit"):
			with self.assertRaises(frappe.ValidationError):
				_assert_timeline_unchanged("PROJECT-TEST", "render-start")

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

	def test_default_ending_preserves_the_final_hold(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-ending-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "ended.mp4"
			_make_video(source, 6, color="white")
			profile = {"width": 320, "height": 240, "fps": 24.0}

			_apply_ending(source, output, profile, temp_path)

			_validate_normalized_video(output, profile, expected_frames=144)
			before, after = _mean_luma(output, 2.0), _mean_luma(output, 5.92)
			self.assertGreater(before, 200)
			self.assertGreater(after, 200)

	def test_explicit_ending_fade_is_honored(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-ending-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "ended.mp4"
			_make_video(source, 4, color="white")
			profile = {"width": 320, "height": 240, "fps": 24.0, "ending_fade_seconds": 0.4}

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
		[
			"ffmpeg",
			"-v",
			"error",
			"-ss",
			str(seconds),
			"-i",
			str(path),
			"-frames:v",
			"1",
			"-vf",
			"format=gray,crop=iw:ih/3,scale=1:1:flags=area",
			"-f",
			"rawvideo",
			"-",
		],
		capture_output=True,
		check=True,
	).stdout
	return output[0]


class TestSceneCaptions(FrappeTestCase):
	def test_caption_cues_cover_every_captioned_scene(self):
		project = frappe._dict(show_captions=1)
		clips = [
			frappe._dict(shot="SHOT-1", timeline_start_frame=0),
			frappe._dict(shot="SHOT-2", timeline_start_frame=48),
		]
		with patch(
			"joymedia.services.editing.export.frappe.get_all",
			return_value=[
				frappe._dict(name="SHOT-1", caption="DÀY DẶN 4 LỚP"),
				frappe._dict(name="SHOT-2", caption="100% BỘT GỖ TỰ NHIÊN"),
			],
		):
			cues = _caption_cues(project, clips, [48, 72], [0, 0], True, 24)

		self.assertEqual(
			[(0.0, 2.0, "DÀY DẶN 4 LỚP"), (2.0, 5.0, "100% BỘT GỖ TỰ NHIÊN")],
			cues,
		)

	def test_caption_shows_in_the_top_band_during_its_scene(self):
		with tempfile.TemporaryDirectory(prefix="joymedia-caption-") as temp_dir:
			temp_path = Path(temp_dir)
			source = temp_path / "source.mp4"
			output = temp_path / "captioned.mp4"
			_make_video(source, 6, color="black")
			profile = {"width": 320, "height": 240, "fps": 24.0}

			_apply_ending(source, output, profile, temp_path, [(0.0, 4.0, "Không gian sống xanh")])

			def lower_third(seconds):
				pixels = subprocess.run(
					[
						"ffmpeg",
						"-v",
						"error",
						"-ss",
						str(seconds),
						"-i",
						str(output),
						"-frames:v",
						"1",
						"-vf",
						"format=gray,crop=iw:ih/6:0:ih*0.04",
						"-f",
						"rawvideo",
						"-",
					],
					capture_output=True,
					check=True,
				).stdout
				return max(pixels)

			self.assertLess(lower_third(0.1), 40)
			self.assertGreater(lower_third(2.0), 150)
			self.assertLess(lower_third(5.0), 40)


class TestPositionedGaps(FrappeTestCase):
	def test_gaps_and_tail_hold_neighbouring_frames_instead_of_black(self):
		profile = {"width": 320, "height": 240, "fps": 24.0}
		with tempfile.TemporaryDirectory(prefix="joymedia-gaps-") as temp_dir:
			temp_path = Path(temp_dir)
			paths = []
			for index, seconds in enumerate((3, 5, 5)):
				path = temp_path / f"clip{index}.mp4"
				_make_video(path, seconds, color="white")
				paths.append(path)
			# 0-3s, gap 3-4s, 4-9s, gap 9-10s, 10-15s, tail gap to 18s.
			clips = [frappe._dict(timeline_start_frame=start * 24) for start in (0, 4, 10)]
			output = temp_path / "out.mp4"
			_render_positioned_sequence(paths, clips, [72, 120, 120], output, profile, total_frames=18 * 24)

			_validate_normalized_video(output, profile, expected_frames=18 * 24)
			for second in (3.5, 9.5, 17):
				self.assertGreater(_mean_luma(output, second), 200, f"black footage at {second}s")


class TestCaptionText(FrappeTestCase):
	def test_a_production_label_in_front_of_the_words_is_not_shown(self):
		from joymedia.services.editing.export import caption_text

		self.assertEqual("Mua ngay", caption_text("CTA:Mua ngay"))
		self.assertEqual("Mua ngay", caption_text(" cta : Mua ngay "))
		self.assertEqual("ĐA NĂNG & TIỆN LỢI", caption_text("ĐA NĂNG & TIỆN LỢI"))
		self.assertEqual("Ctrl the mess", caption_text("Ctrl the mess"))
		self.assertEqual("", caption_text(None))
