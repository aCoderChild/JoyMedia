from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.api.reviews import apply_shot_review_revision, submit_shot_review, sync_shot_review_status
from joymedia.services.test_timeline_editor import _create_output_version, _create_workflow


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
		self.shot.db_set("selected_output_asset_version", self.output.name, update_modified=False)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	@patch("joymedia.services.ai_director.generate_review_revision")
	def test_rejection_is_bound_to_selected_output_and_can_apply_revision(self, generate_revision):
		generate_revision.return_value = {"generation_prompt": "Correct product geometry and smooth motion."}

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

		applied = apply_shot_review_revision(
			self.project.name, self.shot.name, review.name, regenerate=False
		)
		self.assertTrue(applied["applied"])
		self.assertEqual(
			"Correct product geometry and smooth motion.",
			frappe.db.get_value("Shot", self.shot.name, "generation_prompt"),
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

	def test_review_rejects_attempt_not_owned_by_shot(self):
		with self.assertRaises(frappe.ValidationError):
			submit_shot_review(
				self.project.name, self.shot.name, "Approved", generation_attempt="ATT-NOT-THIS-SHOT"
			)
