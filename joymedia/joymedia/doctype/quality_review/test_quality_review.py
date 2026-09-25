from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from .quality_review import QualityReview, regenerate_shot_from_ui


class TestQualityReview(FrappeTestCase):
	def test_approval_promotes_and_selects_the_reviewed_artifact(self):
		review = frappe.new_doc("Quality Review")
		review.generation_artifact = "GART-00001"
		review.reviewer = "Administrator"
		review.reviewed_at = "2026-09-18 00:00:00"
		review.status = "Approved"
		review.db_set = MagicMock()
		artifact = frappe._dict(name="GART-00001", generation_attempt="ATT-00001")
		attempt = frappe._dict(
			name="ATT-00001",
			generation_job="JOB-00001",
			output_artifact="GART-00001",
			status="Completed",
		)
		job = frappe._dict(name="JOB-00001", generation_run=None, shot_specification="SHOT-00001")
		shot = MagicMock(selected_output_asset_version=None)

		with (
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.get_doc",
				side_effect=[artifact, attempt, job, shot],
			),
			patch(
				"joymedia.services.artifact_service.promote_artifact",
				return_value={"asset_version": "ASTV-00001"},
			) as promote_artifact,
		):
			QualityReview._apply_review_outcome(review)

		self.assertEqual(shot.selected_output_asset_version, "ASTV-00001")
		shot.db_set.assert_called_once_with(
			"selected_output_asset_version", "ASTV-00001", update_modified=False
		)
		promote_artifact.assert_called_once_with("GART-00001")
		review.db_set.assert_called_once_with("asset_version", "ASTV-00001", update_modified=False)

	def test_rejection_keeps_a_temporary_artifact(self):
		review = frappe.new_doc("Quality Review")
		review.generation_artifact = "GART-00001"
		review.status = "Rejected"
		shot = MagicMock(selected_output_asset_version=None)
		artifact = MagicMock(lifecycle_status="Temporary", promoted_asset_version=None)
		artifact.name = "GART-00001"
		artifact.generation_attempt = "ATT-00001"
		attempt = frappe._dict(name="ATT-00001", generation_job="JOB-00001")
		job = frappe._dict(name="JOB-00001", shot_specification="SHOT-00001")

		with patch(
			"joymedia.joymedia.doctype.quality_review.quality_review.frappe.get_doc",
			side_effect=[artifact, attempt, job, shot],
		):
			QualityReview._apply_review_outcome(review)

		self.assertEqual(artifact.lifecycle_status, "Temporary")
		artifact.save.assert_not_called()
		shot.db_set.assert_not_called()

	def test_rejected_review_creates_and_submits_a_qa_retry(self):
		review = frappe._dict(name="QREV-00001", status="Rejected", generation_artifact="GART-00001")
		retry_attempt = frappe._dict(name="ATT-00002")
		artifact = frappe._dict(name="GART-00001", generation_attempt="ATT-00001")

		with (
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.has_permission"
			),
			patch(
				"joymedia.joymedia.doctype.quality_review.quality_review.frappe.get_doc",
				side_effect=[review, artifact],
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.create_qa_retry_attempt_internal",
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
