from unittest.mock import MagicMock, patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from .quality_review import QualityReview, regenerate_shot_from_ui


class TestQualityReview(FrappeTestCase):
	def test_scores_must_be_normalized(self):
		review = frappe._dict(
			visual_quality_score=1.01,
			identity_score=0.0,
			temporal_consistency_score=1.0,
			prompt_adherence_score=None,
		)

		with self.assertRaises(ValidationError):
			QualityReview._validate_scores(review)

	def test_score_boundaries_are_valid(self):
		review = frappe._dict(
			visual_quality_score=0.0,
			identity_score=1.0,
			temporal_consistency_score=0.92,
			prompt_adherence_score=None,
		)

		QualityReview._validate_scores(review)

	def test_approval_promotes_and_selects_the_reviewed_artifact(self):
		review = frappe.new_doc("Quality Review")
		review.shot_specification = "SHOT-00001"
		review.generation_attempt = "ATT-00001"
		review.generation_artifact = "GART-00001"
		review.review_type = "Human"
		review.reviewer = "Administrator"
		review.status = "Approved"
		review.db_set = MagicMock()
		shot = MagicMock(selected_output_asset_version=None)

		with (
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.db.get_value",
					side_effect=[
						frappe._dict(
							generation_job="JOB-00001",
							output_artifact="GART-00001",
							status="Completed",
						),
						"SHOT-00001",
						"ATT-00001",
						"JOB-00001",
						None,
					],
			),
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.get_doc",
				return_value=shot,
			),
			patch(
				"joymedia.services.artifact_service.promote_artifact",
				return_value={"asset_version": "ASTV-00001"},
			) as promote_artifact,
		):
			QualityReview.validate(review)
			QualityReview.on_update(review)

		self.assertEqual(shot.selected_output_asset_version, "ASTV-00001")
		shot.save.assert_called_once_with(ignore_permissions=True)
		promote_artifact.assert_called_once_with("GART-00001")
		review.db_set.assert_called_once_with("asset_version", "ASTV-00001", update_modified=False)

	def test_rejection_expires_a_temporary_artifact(self):
		review = frappe.new_doc("Quality Review")
		review.shot_specification = "SHOT-00001"
		review.generation_artifact = "GART-00001"
		review.status = "Rejected"
		shot = MagicMock(selected_output_asset_version=None)
		artifact = MagicMock(lifecycle_status="Temporary", promoted_asset_version=None)

		with patch(
			"joymedia.joymedia.doctype.quality_review.quality_review.frappe.get_doc",
			side_effect=[shot, artifact],
		):
			QualityReview._apply_review_outcome(review)

		self.assertEqual(artifact.lifecycle_status, "Expired")
		artifact.save.assert_called_once_with(ignore_permissions=True)
		shot.save.assert_not_called()

	def test_rejected_review_creates_and_submits_a_qa_retry(self):
		review = frappe._dict(name="QREV-00001", status="Rejected", generation_attempt="ATT-00001")
		retry_attempt = frappe._dict(name="ATT-00002")

		with (
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.has_permission"
			),
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.get_doc",
				return_value=review,
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.create_qa_retry_attempt",
				return_value=retry_attempt,
			) as create_retry,
			patch("joymedia.services.generation_runner.submit_attempt", return_value={"prompt_id": "prompt-1"}) as submit,
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.db.get_value",
				return_value="Queued",
			),
			patch("joymedia.joymedia.doctype.quality_review.quality_review.frappe.db.commit"),
		):
			result = regenerate_shot_from_ui(review.name)

		create_retry.assert_called_once_with("ATT-00001", "Human Review Rejection")
		submit.assert_called_once_with("ATT-00002")
		self.assertEqual(result["name"], "ATT-00002")
