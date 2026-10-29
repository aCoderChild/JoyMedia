from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.api.projects import generate_project_video
from joymedia.services.generation.automation import current_delivery


class TestGenerationPreview(TestCase):
	def test_explicit_review_freezes_preview_policy_and_restores_context(self):
		project = Mock()

		def generate():
			self.assertEqual("review", current_delivery()["export_purpose"])
			self.assertEqual("required", current_delivery()["quality_review"])
			return {"run": "preview"}

		project.generate_end_to_end.side_effect = generate
		with patch("frappe.get_doc", return_value=project):
			self.assertEqual({"run": "preview"}, generate_project_video("project", purpose="review"))
		self.assertIsNone(current_delivery())

	def test_ordinary_generation_and_permission_errors_keep_their_policy(self):
		project = Mock()

		def generate():
			self.assertIsNone(current_delivery())
			raise frappe.PermissionError("read only")

		project.generate_end_to_end.side_effect = generate
		with patch("frappe.get_doc", return_value=project), self.assertRaises(frappe.PermissionError):
			generate_project_video("project")
		self.assertIsNone(current_delivery())

	def test_unknown_purpose_cannot_authorize_generation(self):
		project = Mock()
		with patch("frappe.get_doc", return_value=project), self.assertRaises(ValueError):
			generate_project_video("project", purpose="release")
		project.generate_end_to_end.assert_not_called()
