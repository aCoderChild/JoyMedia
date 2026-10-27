from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.keyframes.product_review import (
	assert_product_frame_ready,
	can_auto_approve_product_frame,
)


class TestProductFrameAdmission(TestCase):
	def setUp(self):
		self.shot = frappe._dict(
			name="SHOT-TEST",
			shot_number=5,
			keyframe_status="Pending Review",
			keyframe_signature="current",
			consistency_status="Passed",
			consistency_notes="",
			generation_inputs=[
				frappe._dict(reference_role="Product", asset_version="PRODUCT"),
				frappe._dict(reference_role="first_frame", asset_version="FRAME"),
			],
		)

	@patch("joymedia.services.keyframes.stage.keyframe_signature", return_value="current")
	@patch("joymedia.services.keyframes.product_review.assert_candidate_current", return_value=True)
	def test_explicit_product_requires_current_approval_and_clean_review(self, candidate, signature):
		project = object()
		with self.assertRaisesRegex(ValueError, "needs review and approval"):
			assert_product_frame_ready(project, self.shot)
		self.shot.keyframe_status = "Approved"
		self.shot.consistency_status = "Checking"
		with self.assertRaisesRegex(ValueError, "unresolved visual findings"):
			assert_product_frame_ready(project, self.shot)
		self.shot.consistency_status = "Needs Review"
		self.shot.consistency_notes = "Critical geometry: product floats"
		with self.assertRaisesRegex(ValueError, "unresolved visual findings"):
			assert_product_frame_ready(project, self.shot)
		self.shot.consistency_status = "Passed"
		self.shot.consistency_notes = ""
		assert_product_frame_ready(project, self.shot)
		candidate.assert_called_once_with(project, self.shot, "FRAME")

	@patch("joymedia.services.keyframes.stage.keyframe_signature", return_value="new")
	def test_changed_scene_invalidates_earlier_approval(self, signature):
		self.shot.keyframe_status = "Approved"
		with self.assertRaisesRegex(ValueError, "needs review and approval"):
			assert_product_frame_ready(object(), self.shot)

	def test_video_preflight_stops_before_gpu_for_unreviewed_product(self):
		from joymedia.services.generation.preparation import validate_generation_preflight

		project = object()
		with (
			patch("frappe.get_doc", return_value=self.shot),
			patch(
				"joymedia.services.keyframes.product_review.assert_product_frame_ready",
				side_effect=ValueError("product opening needs review"),
			) as guard,
		):
			with self.assertRaisesRegex(ValueError, "needs review"):
				validate_generation_preflight(project, object(), [frappe._dict(name="SHOT-TEST")])
		guard.assert_called_once_with(project, self.shot)

	def test_estimated_scale_never_receives_unattended_approval(self):
		self.shot.consistency_status = "Passed"
		measured = frappe._dict(
			analysis_json=frappe.as_json(
				{
					"product_first_frame_candidate": {
						"contact": {
							"geometry": {"scale_evidence": {"product_width_mm": 200, "support_width_mm": 800}}
						}
					}
				}
			)
		)
		estimated = frappe._dict(
			analysis_json=frappe.as_json(
				{"product_first_frame_candidate": {"contact": {"geometry": {"scale_evidence": None}}}}
			)
		)
		with patch("frappe.get_doc", return_value=estimated):
			self.assertFalse(can_auto_approve_product_frame(object(), self.shot))
		with (
			patch("frappe.get_doc", return_value=measured),
			patch("joymedia.services.keyframes.product_review.assert_candidate_current", return_value=True),
		):
			self.assertTrue(can_auto_approve_product_frame(object(), self.shot))
