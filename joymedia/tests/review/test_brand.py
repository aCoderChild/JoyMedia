from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.review.brand import approval_signature, approve_scene_brand, review_state


class TestBrandReview(TestCase):
	def test_approval_is_invalidated_by_a_new_take_or_reference(self):
		refs = [{"reference_role": "Product", "asset_version": "PACK-1"}]
		shot = frappe._dict(
			selected_output_asset_version="TAKE-1",
			brand_approval_signature=approval_signature("TAKE-1", refs),
		)
		self.assertEqual(review_state(shot, refs)["status"], "Approved")
		shot.selected_output_asset_version = "TAKE-2"
		self.assertEqual(review_state(shot, refs)["status"], "Needs Review")
		shot.selected_output_asset_version = "TAKE-1"
		self.assertEqual(
			review_state(shot, [{**refs[0], "asset_version": "PACK-2"}])["status"], "Needs Review"
		)

	def test_automatic_pass_does_not_approve_branding(self):
		shot = frappe._dict(selected_output_asset_version="TAKE-1", consistency_status="Passed")
		self.assertEqual(
			review_state(shot, [{"reference_role": "Character", "asset_version": "BEAR"}])["status"],
			"Needs Review",
		)

	def test_stale_browser_take_cannot_be_approved(self):
		from unittest.mock import Mock

		project = Mock(name="Project")
		project.name = "PROJECT"
		shot = frappe._dict(media_project="PROJECT", selected_output_asset_version="TAKE-2")
		with (
			patch.object(frappe, "get_doc", side_effect=[project, shot]),
			patch.object(frappe.db, "sql"),
			patch.object(frappe.db, "set_value") as write,
			patch.object(frappe, "throw", side_effect=ValueError),
		):
			with self.assertRaises(ValueError):
				approve_scene_brand("PROJECT", "SHOT", "TAKE-1")
			project._require_write_access.assert_called_once()
			write.assert_not_called()
