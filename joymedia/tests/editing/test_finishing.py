import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.editing import finishing as finishing
from joymedia.services.editing.composer import _validate_normalized_video


def _fake_comfyui_chunk(chunk_path, kept):
	"""Stand-in for ESRGAN x2 + RIFE x5 + every 2nd frame + overlap trim: same frames and size."""
	output = Path(chunk_path).with_suffix(".fake.mp4")
	subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-y",
			"-i",
			str(chunk_path),
			"-vf",
			f"scale=iw*2:ih*2,fps=60,tpad=stop_mode=clone:stop_duration=1,trim=end_frame={kept}",
			"-c:v",
			"libx264",
			"-pix_fmt",
			"yuv420p",
			str(output),
		],
		check=True,
	)
	return output.read_bytes()


def _frame_count(path):
	import subprocess as _sp

	out = _sp.run(
		[
			"ffprobe",
			"-v",
			"error",
			"-count_frames",
			"-select_streams",
			"v:0",
			"-show_entries",
			"stream=nb_read_frames",
			"-of",
			"csv=p=0",
			str(path),
		],
		capture_output=True,
		text=True,
	)
	return int(out.stdout.strip())


class TestFinishing(FrappeTestCase):
	def test_studio_profiles(self):
		delivery = {"width": 1920, "height": 1080, "fps": 24.0}
		self.assertEqual({"width": 2560, "height": 1440, "fps": 60.0}, finishing.studio_profile(delivery))
		self.assertEqual({"width": 1280, "height": 720, "fps": 24.0}, finishing.render_profile(delivery))
		self.assertEqual(
			{"width": 1440, "height": 2560, "fps": 60.0},
			finishing.studio_profile({"width": 1080, "height": 1920, "fps": 24.0}),
		)
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
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-f",
					"lavfi",
					"-i",
					"testsrc=s=160x90:r=24:d=2.4167",
					"-frames:v",
					"58",
					"-c:v",
					"libx264",
					"-pix_fmt",
					"yuv420p",
					str(source),
				],
				check=True,
			)

			with patch.object(finishing, "_finish_chunk", side_effect=_fake_comfyui_chunk) as finish_chunk:
				finishing.finish_video(source, output, 58, 24.0, temp_path)

			self.assertEqual(3, finish_chunk.call_count)
			# Each chunk but the last carries the next chunk's first frame.
			self.assertEqual(
				[25, 25, 10], [_frame_count(call.args[0]) for call in finish_chunk.call_args_list]
			)
			_validate_normalized_video(
				output,
				{"width": 320, "height": 180, "fps": 60.0},
				expected_frames=finishing.finished_frame_count(58, 24),
			)


class TestFinishingProfile(unittest.TestCase):
	def test_declared_graph_uses_shared_binding_and_execution_path(self):
		import json

		from joymedia.patches.register_studio_finishing import GRAPH
		from joymedia.services.workflows.resolver import build_execution_workflow

		profile = json.loads(GRAPH.read_text())
		profile["workflow_json"] = json.dumps(profile["workflow_json"])
		profile["execution_spec"] = json.dumps(profile["execution_spec"])
		version = frappe._dict(profile)
		version.bindings = [frappe._dict(b) for b in profile["bindings"]]
		graph = build_execution_workflow(
			version,
			inputs={"source_video": "clip.mp4"},
			seed=0,
			width=720,
			height=900,
			fps=60,
			frame_count=58,
			output_prefix="review/finish",
		)
		self.assertEqual("clip.mp4", graph["load"]["inputs"]["video"])
		self.assertEqual(58, graph["trim"]["inputs"]["length"])
		self.assertEqual("review/finish", graph["joymedia_save"]["inputs"]["filename_prefix"])
