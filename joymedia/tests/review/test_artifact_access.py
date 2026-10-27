from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.access import artifact_permission, artifact_query


class TestArtifactAccess(FrappeTestCase):
	def test_held_clips_are_readable_exactly_where_their_project_is(self):
		doc = frappe._dict(generation_attempt="ATT-TEST")
		with (
			patch("frappe.get_roles", return_value=["JoyMedia User"]),
			patch("frappe.db.sql", return_value=[("PRJ-TEST",)]),
			patch("frappe.has_permission", return_value=True) as project_permission,
		):
			self.assertTrue(artifact_permission(doc, "client@example.com", "read"))
			project_permission.assert_called_with(
				"Media Project", "read", doc="PRJ-TEST", user="client@example.com"
			)
			self.assertFalse(artifact_permission(doc, "client@example.com", "write"))
		with (
			patch("frappe.get_roles", return_value=["JoyMedia User"]),
			patch("frappe.db.sql", return_value=[]),
		):
			self.assertFalse(artifact_permission(doc, "client@example.com", "read"))

	def test_lists_are_limited_to_own_projects_except_for_staff(self):
		with patch("frappe.get_roles", return_value=["JoyMedia User"]):
			self.assertIn("p.owner = 'client@example.com'", artifact_query("client@example.com"))
		with patch("frappe.get_roles", return_value=["JoyMedia Specialist"]):
			self.assertEqual("", artifact_query("staff@example.com"))
