import hashlib
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from .generation_workflow import GenerationWorkflow

Workflow = GenerationWorkflow


class TestWorkflow(FrappeTestCase):
	def test_workflow_hash_uses_canonical_json_and_generic_metadata(self):
		doc = frappe.new_doc("Generation Workflow")
		doc.workflow_key = "test_workflow"
		doc.adapter_key = "comfyui_generic"
		doc.workflow_json = '{"save":{"class_type":"SaveImage","inputs":{"filename_prefix":""}}}'
		doc.execution_spec = '{"parameters":[],"metadata":{"frame_count":90,"output_fps":30},"outputs":{"primary":{"node_key":"save","media_type":"Image"}}}'
		Workflow.validate(doc)
		self.assertEqual(doc.frame_count, 90)
		self.assertEqual(doc.output_fps, 30)
		self.assertEqual(doc.workflow_hash, hashlib.sha256(b'{"save":{"class_type":"SaveImage","inputs":{"filename_prefix":""}}}').hexdigest())

	def test_invalid_binding_is_rejected(self):
		doc = frappe.new_doc("Generation Workflow")
		doc.workflow_key = "test_workflow"
		doc.adapter_key = "comfyui_generic"
		doc.workflow_json = '{"actual_loader":{"class_type":"LoadImage","inputs":{"image_path":""}},"save":{"class_type":"SaveImage","inputs":{"filename_prefix":""}}}'
		doc.execution_spec = '{"parameters":[],"outputs":{"primary":{"node_key":"save","media_type":"Image"}}}'
		doc.append("bindings", {"binding_key": "first_frame", "node_key": "missing_loader", "input_name": "image", "required_input_role": "First Frame", "value_type": "File Path", "required": 1})
		with self.assertRaises(frappe.ValidationError):
			Workflow.validate(doc)

	def test_unsupported_adapter_is_rejected(self):
		doc = frappe.new_doc("Generation Workflow")
		doc.workflow_key = "unsupported"
		doc.adapter_key = "missing_adapter"
		doc.workflow_json = '{}'
		with self.assertRaises(frappe.ValidationError):
			Workflow.validate(doc)

	def test_workflow_content_cannot_change_after_creation(self):
		doc = frappe.new_doc("Generation Workflow")
		doc.name = "WF-00001"
		doc._doc_before_save = frappe._dict(name="WF-00001", workflow_key="product_showcase")
		with patch.object(doc, "has_value_changed", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				Workflow._validate_immutable_content(doc)

	def test_workflow_identity_cannot_change_after_creation(self):
		doc = frappe.new_doc("Generation Workflow")
		doc.name = "WF-00001"
		doc._doc_before_save = frappe._dict(name="WF-00001", workflow_key="product_showcase")
		with patch.object(doc, "has_value_changed", side_effect=lambda fieldname: fieldname == "workflow_key"):
			with self.assertRaises(frappe.ValidationError):
				Workflow._validate_immutable_content(doc)
