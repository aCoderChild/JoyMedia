from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from .media_specification import MediaSpecification


class TestMediaSpecification(FrappeTestCase):
	def test_generation_setup_resolves_default_workflow(self):
		specification = _existing_specification(status="Draft", workflow=None)
		specification.has_value_changed = lambda fieldname: True

		with patch(
			"joymedia.joymedia.doctype.media_specification.media_specification.get_latest_valid_workflow",
			return_value=frappe._dict(name="WF-00001"),
		):
			MediaSpecification._resolve_generation_setup(specification)

		self.assertEqual("WF-00001", specification.workflow)

	def test_ready_specification_requires_workflow(self):
		with self.assertRaises(ValidationError):
			MediaSpecification.validate_generation_setup(_existing_specification(status="Ready"))

	def test_ready_specification_rejects_non_executable_workflow(self):
		specification = _existing_specification(status="Ready", workflow="WF-00001")
		with patch(
			"joymedia.joymedia.doctype.media_specification.media_specification.frappe.get_doc",
			return_value=frappe._dict(name="WF-00001"),
		), patch(
			"joymedia.services.workflow_resolver.validate_workflow_bindings",
			side_effect=ValidationError("invalid workflow"),
		):
			with self.assertRaises(ValidationError):
				MediaSpecification.validate_generation_setup(specification)

	def test_ready_specification_accepts_executable_workflow(self):
		specification = _existing_specification(status="Ready", workflow="WF-00001")
		with patch(
			"joymedia.joymedia.doctype.media_specification.media_specification.frappe.get_doc",
			return_value=frappe._dict(name="WF-00001"),
		), patch(
			"joymedia.services.workflow_resolver.validate_workflow_bindings",
		):
			MediaSpecification.validate_generation_setup(specification)

	def test_ready_specification_cannot_return_to_draft(self):
		specification = _existing_specification(status="Draft")
		specification._doc_before_save = frappe._dict(status="Ready")
		with self.assertRaises(ValidationError):
			MediaSpecification._validate_version_immutability(specification)

	def test_execution_contract_cannot_change_after_a_run_exists(self):
		specification = _existing_specification(workflow="WF-00002")
		specification._doc_before_save = frappe._dict(
			status="Ready",
			media_project="PROJ-00001",
			version_number=1,
			workflow="WF-00001",
			total_duration_seconds=None,
			delivery_preset=None,
			delivery_width=None,
			delivery_height=None,
			generation_instructions=None,
		)
		with patch(
			"joymedia.joymedia.doctype.media_specification.media_specification.frappe.db.exists",
			return_value=True,
		):
			with self.assertRaises(ValidationError):
				MediaSpecification._validate_version_immutability(specification)

	def test_identity_cannot_change_after_creation(self):
		specification = _existing_specification(media_project="PROJ-00002")
		specification._doc_before_save = frappe._dict(
			status="Draft", media_project="PROJ-00001", version_number=1
		)
		with self.assertRaises(ValidationError):
			MediaSpecification._validate_version_immutability(specification)


def _existing_specification(**values):
	defaults = {
		"name": "SPEC-00001",
		"status": "Ready",
		"media_project": "PROJ-00001",
		"version_number": 1,
		"workflow": None,
		"total_duration_seconds": None,
		"delivery_preset": None,
		"delivery_width": None,
		"delivery_height": None,
		"generation_instructions": None,
	}
	defaults.update(values)
	specification = frappe._dict(defaults)
	specification.is_new = lambda: False
	specification.get_doc_before_save = lambda: specification._doc_before_save
	return specification
