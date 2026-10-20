import subprocess
import tempfile
import unittest
from pathlib import Path

from joymedia.services.editing.graphics import apply_graphic_overlays, layer_diagram_plan, requested_graphics, paper_layer_illustration


class TestLayerDiagram(unittest.TestCase):
	def test_bonded_edge_reveal_has_motion_and_rejects_invalid_progress(self):
		import numpy as np
		closed = np.array(paper_layer_illustration((360,640),4,progress=0))
		opened = np.array(paper_layer_illustration((360,640),4,progress=1))
		self.assertGreater(np.count_nonzero(np.any(closed!=opened,axis=2)),500)
		for progress in (-1,2,float('nan'),True):
			with self.assertRaises(ValueError):paper_layer_illustration((128,256),4,progress=progress)

	def test_source_graphic_survives_simplification_of_motion_prompt(self):
		source = {"selected_demo": {"scenes": [{"beat_name": "Demonstration", "action": "Chèn đồ họa mô tả 4 lớp giấy mỏng."}]}}
		self.assertEqual(requested_graphics(source, "Demonstration", "One slow wipe.", 5)[0]["layers"], 4)
		source["selected_demo"]["scenes"][0]["action"] = "One slow wipe."
		self.assertEqual(requested_graphics(source, "Demonstration", "Graphic of 4 layers.", 5), [])

	def test_only_an_explicit_graphic_request_creates_a_counted_insert(self):
		self.assertEqual([], layer_diagram_plan("Four layers of soft tissue absorb water.", 5))
		self.assertEqual([], layer_diagram_plan("Macro close-up of a tissue sheet.", 5))
		self.assertEqual([], layer_diagram_plan("Graphic of 400 layers.", 5))
		self.assertEqual([{"type": "paper_layers", "layers": 4, "start_seconds": 3, "duration_seconds": 1}], layer_diagram_plan("Macro/graphic shows four layers of thin paper stacked.", 5))
		self.assertEqual(4, layer_diagram_plan("Chèn đồ họa mô tả 4 lớp giấy mỏng.", 5)[0]["layers"])

	def test_single_sheet_cutaway_insert_preserves_timing_and_frame_count(self):
		with tempfile.TemporaryDirectory() as folder:
			video, output = Path(folder) / "source.mp4", Path(folder) / "graphic.mp4"
			subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=128x256:r=24:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
			apply_graphic_overlays(video, layer_diagram_plan("Graphic of 4 layers", 4), output, {"fps": 24, "width": 128, "height": 256}, 96)
			raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
			stride = 128 * 256 * 3
			self.assertEqual(96 * stride, len(raw))
			for index in (0, 47, 72, 95):
				pixel = raw[index * stride + (90 * 128 + 64) * 3: index * stride + (90 * 128 + 64) * 3 + 3]
				self.assertLess(pixel[0], 15)
				self.assertGreater(pixel[2], 240)
			# The macro cutaway replaces the frame rather than drawing form bars over an actor.
			pixel = raw[60*stride:60*stride+3]
			self.assertGreater(pixel[0],200)

	def test_standalone_product_cutaway_covers_the_entire_scene(self):
		plan=layer_diagram_plan("Cảnh đồ họa riêng: một tờ giấy có 4 lớp liên kết.", 2)
		self.assertEqual(plan,[{"type":"paper_layers","layers":4,"start_seconds":0,"duration_seconds":2,"language":"vi"}])
		with tempfile.TemporaryDirectory() as folder:
			video,output=Path(folder)/"source.mp4",Path(folder)/"cutaway.mp4"
			subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=c=red:s=128x256:r=24:d=2","-c:v","libx264","-pix_fmt","yuv420p",str(video)],check=True,capture_output=True)
			apply_graphic_overlays(video,plan,output,{"fps":24,"width":128,"height":256},48)
			raw=subprocess.run(["ffmpeg","-v","error","-i",str(output),"-f","rawvideo","-pix_fmt","rgb24","-"],check=True,capture_output=True).stdout
			stride=128*256*3
			self.assertEqual(len(raw),48*stride)
			for frame in range(48):
				self.assertGreater(raw[frame*stride+1],200) # no old red scene at either boundary

	def test_invalid_ply_counts_cannot_become_independent_sheet_stacks(self):
		for count in [True,0,1,13,"4"]:
			with self.subTest(count=count),self.assertRaises(ValueError):paper_layer_illustration((128,256),count)
