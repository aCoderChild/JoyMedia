from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.api.reviews import apply_shot_review_revision, submit_shot_review, sync_shot_review_status
from joymedia.tests.editing.test_timeline import _create_output_version, _create_workflow


class TestShotReviewLoop(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._commit = patch.object(frappe.db, "commit")
		self._commit.start()
		self.addCleanup(self._commit.stop)
		frappe.set_user("Administrator")
		self.project = frappe.get_doc({
			"doctype": "Media Project",
			"project_name": "Review Loop",
			"workflow": _create_workflow(),
			"total_duration_seconds": 2,
			"delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)
		self.shot = frappe.get_doc({
			"doctype": "Shot",
			"media_project": self.project.name,
			"shot_number": 1,
			"generation_prompt": "Original product reveal.",
			"duration_seconds": 2,
		}).insert(ignore_permissions=True)
		asset = frappe.get_doc({
			"doctype": "Media Asset",
			"asset_name": f"{self.shot.name} Output",
			"media_type": "Video",
			"asset_category": "Other",
			"asset_scope": "Project Output",
			"media_project": self.project.name,
		}).insert(ignore_permissions=True)
		self.output = _create_output_version(self.project, "review-output.mp4", 1, asset)[1]
		self.asset = asset
		self.shot.db_set("selected_output_asset_version", self.output.name, update_modified=False)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	@patch("joymedia.services.planning.revisions.generate_review_revision")
	def test_rejection_is_bound_to_selected_output_and_can_apply_revision(self, generate_revision):
		generate_revision.return_value = {
			"generation_prompt": "Correct product geometry and smooth motion.",
			"image_prompt": "The exact product with its correct cap geometry on a clean pedestal.",
		}

		result = submit_shot_review(
			self.project.name,
			self.shot.name,
			"Rejected",
			feedback_notes="The cap changes shape.",
			rejection_category="Continuity Break",
		)
		review = frappe.get_doc("Shot Review", result["review_name"])

		self.assertEqual(self.output.name, review.output_asset_version)
		self.assertEqual("Rejected", frappe.db.get_value("Shot", self.shot.name, "review_status"))
		self.assertEqual("Correct product geometry and smooth motion.", review.ai_suggested_revision)
		self.assertEqual(
			"The exact product with its correct cap geometry on a clean pedestal.",
			review.ai_suggested_image_prompt,
		)

		applied = apply_shot_review_revision(
			self.project.name, self.shot.name, review.name, regenerate=False
		)
		self.assertTrue(applied["applied"])
		self.assertEqual(
			"Correct product geometry and smooth motion.",
			frappe.db.get_value("Shot", self.shot.name, "generation_prompt"),
		)
		self.assertEqual(
			"The exact product with its correct cap geometry on a clean pedestal.",
			frappe.db.get_value("Shot", self.shot.name, "image_prompt"),
		)

	def test_switching_take_restores_only_that_take_review_verdict(self):
		frappe.get_doc({
			"doctype": "Shot Review",
			"shot": self.shot.name,
			"reviewer": "Administrator",
			"verdict": "Approved",
			"output_asset_version": self.output.name,
		}).insert(ignore_permissions=True)

		self.assertEqual("Approved", sync_shot_review_status(self.shot.name))
		self.shot.db_set("selected_output_asset_version", None, update_modified=False)
		self.assertEqual("Pending Review", sync_shot_review_status(self.shot.name))

	def test_automated_approval_never_restores_delivery_approval_when_a_take_is_reselected(self):
		other_output = _create_output_version(self.project, "other-review-output.mp4", 1, self.asset)[1]
		frappe.get_doc({
			"doctype": "Shot Review",
			"shot": self.shot.name,
			"reviewer": "Administrator",
			"review_kind": "Automated",
			"verdict": "Approved",
			"output_asset_version": self.output.name,
		}).insert(ignore_permissions=True)

		self.shot.db_set("selected_output_asset_version", other_output.name, update_modified=False)
		self.assertEqual("Pending Review", sync_shot_review_status(self.shot.name))
		self.shot.db_set("selected_output_asset_version", self.output.name, update_modified=False)
		self.assertEqual("Pending Review", sync_shot_review_status(self.shot.name))

	def test_automated_approval_cannot_satisfy_the_finishing_gate(self):
		from joymedia.services.editing.post_production import _require_approved_shots

		frappe.get_doc({
			"doctype": "Shot Review", "shot": self.shot.name, "reviewer": "Administrator",
			"review_kind": "Automated", "verdict": "Approved", "output_asset_version": self.output.name,
		}).insert(ignore_permissions=True)
		self.shot.db_set("review_status", "Approved", update_modified=False)

		with self.assertRaises(frappe.ValidationError):
			_require_approved_shots(self.project.name)

	@patch("joymedia.services.editing.post_production.resume_post_production_if_approved", return_value={"status": "Queued"})
	def test_human_approval_resumes_eligible_finishing(self, resume):
		result = submit_shot_review(self.project.name, self.shot.name, "Approved")
		self.assertEqual("Queued", result["finishing"])
		resume.assert_called_once_with(self.project.name)

	@patch("joymedia.services.editing.post_production.resume_post_production_if_approved", return_value={"status": "Queued"})
	def test_repeated_human_approval_retries_a_deferred_finishing_request(self, resume):
		frappe.get_doc({
			"doctype": "Shot Review", "shot": self.shot.name, "reviewer": "Administrator",
			"review_kind": "Human", "verdict": "Approved", "output_asset_version": self.output.name,
		}).insert(ignore_permissions=True)

		result = submit_shot_review(self.project.name, self.shot.name, "Approved")

		self.assertEqual("Queued", result["finishing"])
		resume.assert_called_once_with(self.project.name)

	@patch("joymedia.services.editing.post_production.resume_post_production_if_approved", side_effect=RuntimeError("worker unavailable"))
	def test_approval_is_saved_when_finishing_cannot_be_requested(self, resume):
		result = submit_shot_review(self.project.name, self.shot.name, "Approved")

		self.assertEqual("Deferred", result["finishing"])
		self.assertEqual("Approved", sync_shot_review_status(self.shot.name))
		resume.assert_called_once_with(self.project.name)

	def test_review_rejects_attempt_not_owned_by_shot(self):
		with self.assertRaises(frappe.ValidationError):
			submit_shot_review(
				self.project.name, self.shot.name, "Approved", generation_attempt="ATT-NOT-THIS-SHOT"
			)
