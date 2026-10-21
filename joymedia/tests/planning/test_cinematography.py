import hashlib
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.intake.cinematography import analyze_video, review_reference
from joymedia.services.planning.camera import (
	BOUNDARY_MOVES,
	camera_intent,
	camera_plan,
	reference_camera_grammar,
)


class TestUpstreamCinematography(TestCase):
	def test_real_cut_detection_preserves_source_geometry_and_evidence(self):
		import cv2
		import numpy as np

		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "reference.avi"
			writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 24, (160, 96))
			self.assertTrue(writer.isOpened())
			rng = np.random.default_rng(17)
			for _shot in range(2):
				background = rng.integers(0, 256, (96, 160, 3), dtype=np.uint8)
				for frame in range(32):
					image = background.copy()
					cv2.rectangle(image, (frame, 35), (frame + 15, 50), (255, 255, 255), -1)
					writer.write(image)
			writer.release()
			result = analyze_video(path)
			self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["source"]["sha256"])
		self.assertEqual((160, 96), (result["video"]["width"], result["video"]["height"]))
		self.assertEqual(64, result["video"]["frame_count"])
		self.assertEqual(2, len(result["shots"]))
		self.assertEqual("image_space_only", result["measurement_space"])
		self.assertNotIn("path", result["video"])
		# A moving foreground object must not become an asserted camera trajectory.
		self.assertNotIn("trajectory", result)
		self.assertTrue(all(abs(s["signature"]["net_dx_pixels"]) < 2 for s in result["shots"]))

	def test_each_advanced_move_needs_both_boundaries_and_permission(self):
		for behavior in sorted(BOUNDARY_MOVES):
			with self.subTest(behavior=behavior):
				shot = {
					"name": "scene",
					"shot_number": 1,
					"motion_plan_json": {
						"camera_intent": camera_intent(
							{
								"behavior": behavior,
								"allow_reframe": True,
								"energy": "brisk",
							}
						)
					},
					"references": [{"reference_role": "first_frame"}],
				}
				self.assertEqual("locked", camera_plan(shot, {})["behavior"])
				shot["references"].append({"reference_role": "last_frame"})
				compiled = camera_plan(shot, {})
				self.assertEqual(behavior, compiled["behavior"])
				self.assertIn("brisk", compiled["direction"])
				shot["motion_plan_json"]["camera_intent"]["allow_reframe"] = False
				self.assertEqual("locked", camera_plan(shot, {})["behavior"])

	def test_conflicting_reviewed_direction_is_not_silently_selected(self):
		base = {
			"version": 1,
			"sources": [{"name": "reference", "sha256": "a" * 64}],
			"notes": ["Observed reference"],
			"moves": {"establish": {"behavior": "pan_left"}},
		}
		other = json.loads(json.dumps(base))
		other["moves"]["establish"]["behavior"] = "truck_left"
		with (
			patch("joymedia.services.intake.cinematography.reference_direction", return_value=([base], [])),
			patch("joymedia.services.intake.references.brand", return_value={"camera_grammar": other}),
			self.assertRaisesRegex(ValueError, "Conflicting"),
		):
			reference_camera_grammar({})

	def test_review_rejects_unselected_reference(self):
		with self.assertRaisesRegex(ValueError, "Select this video"):
			review_reference({"selected_media": []}, "unselected", {})

	def test_review_checks_asset_write_permission_before_changing_shared_direction(self):
		version = frappe._dict(name="selected", media_asset="asset", analysis_json="{}")
		with (
			patch("joymedia.services.intake.cinematography.motion_references", return_value=iter([version])),
			patch("frappe.get_doc") as get_doc,
		):
			get_doc.return_value.check_permission.side_effect = frappe.PermissionError
			with self.assertRaises(frappe.PermissionError):
				review_reference({}, "selected", {})
