import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflow_resolver import _resolve_generation_input


class TestWorkflowResolver(FrappeTestCase):
	def test_human_readable_required_role_resolves_canonical_staged_input(self):
		job = frappe._dict(name="JOB-00001")

		value = _resolve_generation_input(
			job,
			"FIRST FRAME",
			{"first_frame": "first.png"},
		)

		self.assertEqual("first.png", value)
