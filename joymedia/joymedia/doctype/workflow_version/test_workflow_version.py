import hashlib
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from .workflow_version import WorkflowVersion


class TestWorkflowVersion(FrappeTestCase):
	def test_workflow_hash_uses_canonical_json_and_h3_adapter_metadata(self):
		doc = frappe.new_doc("Workflow Version")
		doc.workflow_profile = "WFP-00001"
		doc.workflow_json = '{"save_video":{"inputs":{"frame_rate":30}},"minimax_cond":{"inputs":{"length":90,"height":1920,"width":1080}}}'

		with patch(
			"joymedia.joymedia.doctype.workflow_version.workflow_version.frappe.get_doc",
			return_value=frappe._dict(workflow_code="H3-I2V-TURBO"),
		):
			WorkflowVersion.validate(doc)

		self.assertEqual(
			doc.workflow_hash,
			hashlib.sha256(
				b'{"minimax_cond":{"inputs":{"height":1920,"length":90,"width":1080}},"save_video":{"inputs":{"frame_rate":30}}}'
			).hexdigest(),
		)
		self.assertEqual(doc.frame_count, 90)
		self.assertEqual(doc.output_fps, 30)

	def test_draft_workflow_can_be_saved_while_bindings_are_being_repaired(self):
		doc = frappe.new_doc("Workflow Version")
		doc.workflow_profile = "WFP-00001"
		doc.status = "Draft"
		doc.workflow_json = '{"actual_loader":{"inputs":{"image_path":""}}}'
		doc.append(
			"bindings",
			{
				"binding_key": "first_frame",
				"node_key": "missing_loader",
				"input_name": "image",
				"value_source": "Generation Input",
				"required_input_role": "First Frame",
				"value_type": "File Path",
				"required": 1,
			},
		)

		with patch(
			"joymedia.joymedia.doctype.workflow_version.workflow_version.frappe.get_doc",
			return_value=frappe._dict(workflow_code="H3-I2V-TURBO"),
		):
			WorkflowVersion.validate(doc)

	def test_testing_workflow_rejects_stale_binding(self):
		doc = frappe.new_doc("Workflow Version")
		doc.workflow_profile = "WFP-00001"
		doc.status = "Testing"
		doc.workflow_json = '{"actual_loader":{"inputs":{"image_path":""}}}'
		doc.append(
			"bindings",
			{
				"binding_key": "first_frame",
				"node_key": "missing_loader",
				"input_name": "image",
				"value_source": "Generation Input",
				"required_input_role": "First Frame",
				"value_type": "File Path",
				"required": 1,
			},
		)

		with self.assertRaises(frappe.ValidationError):
			WorkflowVersion.validate(doc)

	def test_production_workflow_content_cannot_change(self):
		doc = frappe.new_doc("Workflow Version")
		doc.name = "WFV-00001"
		doc.status = "Production"
		doc._doc_before_save = frappe._dict(status="Production")
		with patch.object(doc, "has_value_changed", side_effect=lambda fieldname: fieldname == "workflow_json"):
			with self.assertRaises(frappe.ValidationError):
				WorkflowVersion._validate_immutable_content(doc)

	def test_production_workflow_can_be_deprecated_without_content_change(self):
		doc = frappe.new_doc("Workflow Version")
		doc.name = "WFV-00001"
		doc.status = "Deprecated"
		doc._doc_before_save = frappe._dict(status="Production")
		with patch.object(doc, "has_value_changed", return_value=False):
			WorkflowVersion._validate_immutable_content(doc)
