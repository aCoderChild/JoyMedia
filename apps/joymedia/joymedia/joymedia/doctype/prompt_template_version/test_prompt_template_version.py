import hashlib
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from .prompt_template_version import PromptTemplateVersion


class TestPromptTemplateVersion(FrappeTestCase):
	def test_template_hash_uses_template_body(self):
		doc = frappe.new_doc("Prompt Template Version")
		doc.template_body = "A {subject} in {environment}"

		PromptTemplateVersion.validate(doc)

		self.assertEqual(
			doc.template_hash,
			hashlib.sha256(doc.template_body.encode("utf-8")).hexdigest(),
		)

	def test_deprecated_template_cannot_change(self):
		doc = frappe.new_doc("Prompt Template Version")
		doc.name = "PTV-00001"
		doc.status = "Deprecated"
		doc._doc_before_save = frappe._dict(status="Deprecated")
		with patch.object(doc, "has_value_changed", side_effect=lambda fieldname: fieldname == "template_body"):
			with self.assertRaises(frappe.ValidationError):
				PromptTemplateVersion._validate_immutable_content(doc)

	def test_production_template_can_be_deprecated_without_content_change(self):
		doc = frappe.new_doc("Prompt Template Version")
		doc.name = "PTV-00001"
		doc.status = "Deprecated"
		doc._doc_before_save = frappe._dict(status="Production")
		with patch.object(doc, "has_value_changed", return_value=False):
			PromptTemplateVersion._validate_immutable_content(doc)
