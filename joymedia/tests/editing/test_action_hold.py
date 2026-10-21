import json
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from joymedia.services.editing.composer import _with_closing_hold
from joymedia.services.project.context import _compose_end_card


class TestActionHold(TestCase):
	def test_image_preparation_has_no_video_tail_or_minimum_action_duration(self):
		row = {"duration_seconds": 1, "references": [{"reference_role": "Product"}]}
		_compose_end_card([row], keyframe_stage=True)
		self.assertNotIn("closing_hold_seconds", row)
		self.assertNotIn("closing_hold_mode", row)
		_compose_end_card([row])
		self.assertNotIn("closing_hold_seconds", row)

	def test_authored_closing_motion_survives_for_unrelated_products(self):
		for subject in ["vase", "furniture", "mascot"]:
			row = {
				"shot_number": 1,
				"duration_seconds": 5,
				"character_mode": "Draw in scene",
				"references": [{"reference_role": "Product"}],
				"generation_prompt": f"The {subject} turns then holds.",
			}
			_compose_end_card([row])
			self.assertEqual("Draw in scene", row["character_mode"])
			self.assertNotIn("closing_hold_seconds", row)
			self.assertNotIn("closing_hold_mode", row)

	def test_a_short_authored_performance_is_not_replaced_with_a_fixed_tail(self):
		row = {"duration_seconds": 2, "references": [{"reference_role": "Product"}]}
		_compose_end_card([row])
		self.assertNotIn("closing_hold_seconds", row)

	def test_a_source_only_card_requires_an_explicit_static_contract(self):
		row = {
			"duration_seconds": 5,
			"references": [{"reference_role": "Product", "asset_version": "source"}],
			"motion_plan_json": {
				"camera_motion": "locked",
				"scene_contract": {
					"version": 1,
					"entities": [{"id": "p", "label": "the source product"}],
					"properties": [{"entity": "p", "name": "motion", "value": "stationary"}],
				},
			},
		}
		_compose_end_card([row])
		self.assertEqual("source_artwork", row["closing_hold_mode"])
		self.assertEqual(5, row["closing_hold_seconds"])

	def test_static_source_presentation_preserves_the_authored_composition_mode(self):
		for mode in ("Draw in scene", "Paste exact art"):
			row = {
				"character_mode": mode,
				"duration_seconds": 5,
				"references": [{"reference_role": "Product", "asset_version": "source"}],
				"motion_plan_json": {
					"camera_motion": "locked",
					"scene_contract": {
						"version": 1,
						"entities": [{"id": "p", "label": "the source product"}],
						"properties": [{"entity": "p", "name": "motion", "value": "stationary"}],
					},
				},
			}
			_compose_end_card([row])
			self.assertEqual(row["character_mode"], mode)
			self.assertEqual(row["closing_hold_mode"], "source_artwork")

	def test_final_pose_is_frozen_without_returning_to_the_opening_or_changing_length(self):
		with tempfile.TemporaryDirectory() as d:
			path = Path(d) / "motion.mp4"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-f",
					"lavfi",
					"-i",
					"testsrc2=size=128x128:rate=24:duration=5",
					"-c:v",
					"libx264",
					"-pix_fmt",
					"yuv420p",
					str(path),
				],
				check=True,
			)
			with patch("joymedia.services.editing.composer._closing_hold_source", return_value=(2, None)):
				out = _with_closing_hold(path, "run", "shot", {"fps": 24, "width": 128, "height": 128}, 120)
			import cv2
			import numpy as np

			cap = cv2.VideoCapture(str(out))
			frames = []
			while True:
				ok, frame = cap.read()
				if not ok:
					break
				frames.append(frame.astype(float))
			cap.release()
			self.assertEqual(120, len(frames))
			self.assertGreater(np.abs(frames[0] - frames[60]).mean(), 5)
			self.assertLess(np.abs(frames[75] - frames[-1]).mean(), 1)
			self.assertLess(np.abs(frames[71] - frames[72]).mean(), 3)
