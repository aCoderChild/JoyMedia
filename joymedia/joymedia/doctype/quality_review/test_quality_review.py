from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from .quality_review import QualityReview


class TestQualityReview(FrappeTestCase):
	def test_approval_selects_the_reviewed_output(self):
		review = frappe.new_doc("Quality Review")
		review.shot_specification = "SHOT-00001"
		review.generation_attempt = "ATT-00001"
		review.asset_version = "ASTV-00001"
		review.review_type = "Human"
		review.reviewer = "Administrator"
		review.status = "Approved"
		shot = MagicMock(selected_output_asset_version=None)

		with (
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.db.get_value",
				side_effect=[
					frappe._dict(
						generation_job="JOB-00001",
						output_asset_version="ASTV-00001",
						status="Completed",
					),
					"SHOT-00001",
					"JOB-00001",
					None,
				],
			),
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.get_doc",
				return_value=shot,
			),
		):
			QualityReview.validate(review)
			QualityReview.on_update(review)

		self.assertEqual(shot.selected_output_asset_version, "ASTV-00001")
		shot.save.assert_called_once_with(ignore_permissions=True)
