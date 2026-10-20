from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.services.generation.preparation import _pipeline_steps_for_segment
from joymedia.services.planning.h3 import _direct_reference_roles, compile_h3
from joymedia.tests.planning import test_shot_structure


class TestReferenceOnly(TestCase):
	def workflow(self):
		return frappe._dict(
			execution_spec={"capabilities": ["reference_only"]},
			bindings=[
				frappe._dict(required_input_role=r)
				for r in ["character", "product", "environment", "general"]
			],
		)

	def test_picture_numbers_follow_present_bindings_and_omit_absent_roles(self):
		s = frappe._dict(
			references=[
				{"reference_role": "Environment"},
				{"reference_role": "Product"},
				{"reference_role": "Character"},
			]
		)
		text = _direct_reference_roles(s, self.workflow())
		self.assertIn("<Picture 1> controls only the actor identity", text)
		self.assertIn("<Picture 2> controls the same single advertised product", text)
		s.references = [{"reference_role": "General"}]
		self.assertIn(
			"<Picture 1> controls the authored material", _direct_reference_roles(s, self.workflow())
		)
		s.references = []
		with self.assertRaises(ValueError):
			_direct_reference_roles(s, self.workflow())

	@patch("joymedia.services.planning.prompts._mood", return_value="Premium commercial light.")
	@patch("joymedia.services.planning.prompts._identity_guard", return_value="WRONG FIXED FRAME GUARD")
	def test_direct_prompt_never_claims_an_anchored_opening(self, guard, mood):
		s = test_shot_structure.TestShotStructure().scene()
		s.references = [
			{"reference_role": "Character", "asset_version": "A"},
			{"reference_role": "Product", "asset_version": "P"},
		]
		text = compile_h3(
			s, frappe._dict(soundtrack_mode="Sound effects only"), kind="reference", workflow=self.workflow()
		)
		self.assertIn("Generate a oblique close-up opening", text)
		self.assertIn("not a fixed opening frame", text)
		self.assertNotIn("WRONG FIXED FRAME GUARD", text)
		self.assertNotIn("Begin with the supplied opening frame", text)
		self.assertIn("The camera holds", text)

	def test_reference_only_skips_the_unused_image_stage(self):
		stages = [frappe._dict(step_key="image"), frappe._dict(step_key="video")]
		self.assertEqual(
			[(stages[-1], None, None, True)],
			_pipeline_steps_for_segment(stages, reference_only=True, keyframe_job="OLD"),
		)
		self.assertEqual(2, len(_pipeline_steps_for_segment(stages)))

	def test_reference_only_has_no_opening_control_to_approve(self):
		from joymedia.services.review.admission import needs_frame_approval

		scene = {"references": [{"reference_role": "character"}]}
		self.assertTrue(needs_frame_approval({"visual_admission": True}, scene))
		self.assertFalse(needs_frame_approval({"visual_admission": True}, scene, reference_only=True))

	def test_surface_projection_never_pastes_the_photo_background(self):
		import numpy as np

		from joymedia.services.keyframes.source_art import project_surface

		frame = np.full((64, 64, 3), 80, np.uint8)
		art = np.full((32, 32, 3), 255, np.uint8)
		art[8:25, 8:25] = [200, 100, 30]
		result = project_surface(
			frame, art, [[8, 8], [24, 8], [24, 24], [8, 24]], [[20, 20], [40, 20], [40, 40], [20, 40]]
		)
		self.assertTrue(np.array_equal(frame[0, 0], result[0, 0]))
		self.assertTrue(np.array_equal(result[30, 30], [200, 100, 30]))
		with self.assertRaises(ValueError):
			project_surface(
				frame, art, [[8, 8], [24, 8], [24, 24], [8, 24]], [[20, 20], [20, 40], [40, 40], [40, 20]]
			)
