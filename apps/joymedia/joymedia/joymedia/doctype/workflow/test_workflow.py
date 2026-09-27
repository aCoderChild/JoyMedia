import hashlib
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from .workflow import Workflow


class TestWorkflow(FrappeTestCase):
	def test_workflow_hash_uses_canonical_json_and_h3_adapter_metadata(self):
		doc = frappe.new_doc("Workflow")
		doc.workflow_key = "product_showcase"
		doc.workflow_json = '{"save_video":{"inputs":{"frame_rate":30}},"minimax_cond":{"inputs":{"length":90,"height":1920,"width":1080}}}'
		Workflow.validate(doc)
		self.assertEqual(doc.frame_count, 90)
		self.assertEqual(doc.output_fps, 30)
		self.assertEqual(doc.workflow_hash, hashlib.sha256(b'{"minimax_cond":{"inputs":{"height":1920,"length":90,"width":1080}},"save_video":{"inputs":{"frame_rate":30}}}').hexdigest())

	def test_invalid_binding_is_rejected(self):
		doc = frappe.new_doc("Workflow")
		doc.workflow_key = "product_showcase"
		doc.workflow_json = '{"actual_loader":{"inputs":{"image_path":""}}}'
		doc.append("bindings", {"binding_key": "first_frame", "node_key": "missing_loader", "input_name": "image", "value_source": "Generation Input", "required_input_role": "First Frame", "value_type": "File Path", "required": 1})
		with self.assertRaises(frappe.ValidationError):
			Workflow.validate(doc)

	def test_workflow_content_cannot_change_after_creation(self):
		doc = frappe.new_doc("Workflow")
		doc.name = "WF-00001"
		doc._doc_before_save = frappe._dict(name="WF-00001", workflow_key="product_showcase")
		with patch.object(doc, "has_value_changed", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				Workflow._validate_immutable_content(doc)

	def test_workflow_identity_cannot_change_after_creation(self):
		doc = frappe.new_doc("Workflow")
		doc.name = "WF-00001"
		doc._doc_before_save = frappe._dict(name="WF-00001", workflow_key="product_showcase")
		with patch.object(doc, "has_value_changed", side_effect=lambda fieldname: fieldname == "workflow_key"):
			with self.assertRaises(frappe.ValidationError):
				Workflow._validate_immutable_content(doc)
