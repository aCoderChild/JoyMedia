# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from .media_specification import MediaSpecification


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class TestMediaSpecification(FrappeTestCase):
	def test_ready_specification_cannot_return_to_draft(self):
		specification = _existing_specification(status="Draft")
		specification._doc_before_save = frappe._dict(status="Ready")

		with self.assertRaises(ValidationError):
			MediaSpecification._validate_version_immutability(specification)

	def test_execution_contract_cannot_change_after_a_run_exists(self):
		specification = _existing_specification(generation_workflow_version="WFV-00002")
		specification._doc_before_save = frappe._dict(
			status="Ready",
			media_project="PROJ-00001",
			version_number=1,
			generation_workflow_version="WFV-00001",
			prompt_template_version=None,
			total_duration_seconds=None,
			delivery_preset=None,
			delivery_width=None,
			delivery_height=None,
			required_elements=None,
			consistency_requirements=None,
			forbidden_elements=None,
			acceptance_criteria=None,
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
		"generation_workflow_version": None,
		"prompt_template_version": None,
		"total_duration_seconds": None,
		"delivery_preset": None,
		"delivery_width": None,
		"delivery_height": None,
		"required_elements": None,
		"consistency_requirements": None,
		"forbidden_elements": None,
		"acceptance_criteria": None,
	}
	defaults.update(values)
	specification = frappe._dict(defaults)
	specification.is_new = lambda: False
	specification.get_doc_before_save = lambda: specification._doc_before_save
	return specification
