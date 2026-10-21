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
	def test_reference_use_separates_camera_and_subject_action_sources(self):
		from joymedia.services.intake.cinematography import motion_references

		project = {
			"selected_media": [
				{
					"reference_role": "Motion",
					"asset_version": "camera",
					"motion_reference_use": "Camera only",
				},
				{
					"reference_role": "Motion",
					"asset_version": "action",
					"motion_reference_use": "Actions only",
				},
				{"reference_role": "Motion", "asset_version": "both"},
			]
		}

		def value(doctype, name, *args, **kwargs):
			return (
				frappe._dict(name=name, media_asset=name, file=name)
				if doctype == "Asset Version"
				else "Video"
			)

		with patch.object(frappe.db, "get_value", side_effect=value):
			self.assertEqual(
				["camera", "both"], [v.name for v in motion_references(project, purpose="Camera")]
			)
			self.assertEqual(
				["action", "both"], [v.name for v in motion_references(project, purpose="Actions")]
			)
			self.assertEqual(3, len(list(motion_references(project))))

	def test_initial_director_and_revision_entry_receive_reference_policy(self):
		project = frappe.get_doc({"doctype": "Media Project", "product_name": "Supplied product"})
		settings = frappe._dict(
			total_duration_seconds=30,
			generation_mode="Multi-shot",
			global_instructions="Authored brief",
			delivery_width=1920,
			delivery_height=1080,
		)
		with (
			patch(
				"joymedia.joymedia.doctype.media_project.media_project._project_settings",
				return_value=settings,
			),
			patch("joymedia.services.intake.cinematography.ensure_project_camera_analysis") as analyze,
			patch(
				"joymedia.services.planning.camera.camera_planning_rules",
				return_value="Reference camera direction",
			),
			patch("joymedia.services.workflows.routing.automatic_planning_input_contract", return_value=[]),
			patch("joymedia.services.planning.llm.generate_video_plan", return_value={}) as director,
		):
			project._plan_video(
				workflow=frappe._dict(output_fps=24), video_idea="Authored action", story_film=False
			)
			analyze.assert_called_once_with(project)
			self.assertIn(
				"Authored brief\nReference camera direction", director.call_args.kwargs["global_instructions"]
			)
			self.assertIn("motion_plan.shot_structure", director.call_args.kwargs["global_instructions"])
			self.assertEqual("16:9", director.call_args.kwargs["format_preset"])

	def test_frozen_reference_policy_reaches_compiler_without_planner_camera_prose(self):
		structure = {
			"stage": "establish",
			"framing": "wide",
			"angle": "eye_level",
			"subject_motion": "stationary",
			"keep_visible": [],
		}
		shot = {
			"shot_number": 1,
			"motion_plan_json": {"shot_structure": structure},
			"references": [{"reference_role": "first_frame"}, {"reference_role": "last_frame"}],
		}
		grammar = {
			"version": 1,
			"sources": [{"name": "reference", "sha256": "a" * 64}],
			"notes": ["Reference interpretation"],
			"moves": {"establish": {"behavior": "truck_right", "allow_reframe": True}},
		}
		project = {"cinematic_camera": True, "camera_grammar": grammar}
		self.assertEqual("truck_right", camera_plan(shot, project)["behavior"])
		shot["references"].pop()
		self.assertEqual("locked", camera_plan(shot, project)["behavior"])
		shot["motion_plan_json"].pop("shot_structure")
		with self.assertRaisesRegex(ValueError, "semantic shot structure"):
			camera_plan(shot, project)

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
