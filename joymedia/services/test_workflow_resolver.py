from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflow_resolver import _resolve_generation_input, _resolve_runtime_value


class TestWorkflowResolver(FrappeTestCase):
	def test_human_readable_required_role_resolves_canonical_staged_input(self):
		job = frappe._dict(name="JOB-00001")

		value = _resolve_generation_input(
			job,
			"FIRST FRAME",
			{"first_frame": "first.png"},
		)

		self.assertEqual("first.png", value)

	@patch("joymedia.services.workflow_resolver.frappe.get_doc")
	def test_runtime_delivery_dimensions_come_from_media_specification(self, get_doc):
		get_doc.side_effect = [
			frappe._dict(media_specification="SPEC-00001"),
			frappe._dict(delivery_width=1280, delivery_height=720),
		]
		job = frappe._dict(shot_specification="SHOT-00001")

		self.assertEqual(1280, _resolve_runtime_value("delivery_width", job, None))

		get_doc.reset_mock()
		get_doc.side_effect = [
			frappe._dict(media_specification="SPEC-00001"),
			frappe._dict(delivery_width=1280, delivery_height=720),
		]
		self.assertEqual(720, _resolve_runtime_value("delivery_height", job, None))
