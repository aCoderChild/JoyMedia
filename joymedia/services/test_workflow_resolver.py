import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import workflow_profiles
from joymedia.services.workflow_resolver import (
	_SKIP_BINDING,
	_resolve_declared_binding,
	_resolve_input_value,
	_role_slot_index,
	build_execution_workflow,
	get_workflow_input_contract,
	validate_workflow_bindings,
	validate_workflow_for_execution,
)


class TestWorkflowResolver(FrappeTestCase):
	def test_selected_pipeline_supplies_the_keyframe_role_contract(self):
		final_workflow = frappe._dict(name="WF-VIDEO", bindings=[frappe._dict(
			binding_key="first_frame", required_input_role="first_frame", value_type="File Path",
			accepted_media_type="Image", allow_multiple=0, required=1,
		)])
		keyframe_workflow = frappe._dict(name="WF-KEYFRAME", bindings=[
			frappe._dict(binding_key=role, required_input_role=role, value_type="File Paths",
				accepted_media_type="Image", allow_multiple=1, required=0)
			for role in ("person", "product", "environment")
		])
		pipeline = frappe._dict(name="PIPE-TEST", steps=[
			frappe._dict(workflow=keyframe_workflow.name), frappe._dict(workflow=final_workflow.name),
		])
		documents = {
			("Generation Pipeline", "PIPE-TEST"): pipeline,
			("Generation Workflow", keyframe_workflow.name): keyframe_workflow,
		}
		with patch.object(frappe, "get_doc", side_effect=lambda doctype, name: documents[(doctype, name)]):
			contract = workflow_profiles.planning_input_contract(final_workflow, "PIPE-TEST")
		self.assertEqual(["person", "product", "environment"], [row["role"] for row in contract[:3]])

	def test_ordered_bindings_use_declared_role_and_order(self):
		bindings = [
			frappe._dict(binding_key="product_primary", required_input_role="product_reference",
				value_type="File Path", required=1, allow_multiple=0),
			frappe._dict(binding_key="product_secondary", required_input_role="product_reference",
				value_type="File Path", required=0, allow_multiple=0),
		]
		workflow = frappe._dict(bindings=bindings)
		contract = get_workflow_input_contract(workflow)
		self.assertEqual((1, 2), (contract[0]["min_count"], contract[0]["max_count"]))
		self.assertEqual((0, 1), (_role_slot_index(bindings, bindings[0]), _role_slot_index(bindings, bindings[1])))
		values = {"product_reference": ["one.png", "two.png"]}
		self.assertEqual("one.png", _resolve_declared_binding(bindings[0], values))
		self.assertEqual("two.png", _resolve_declared_binding(bindings[1], values, role_slot=1))

	def test_references_for_repeated_scalar_bindings_keep_each_slot(self):
		workflow = frappe._dict(bindings=[
			frappe._dict(binding_key="product_primary", required_input_role="product_reference",
				value_type="File Path", required=1, allow_multiple=0, accepted_media_type="Image"),
			frappe._dict(binding_key="product_secondary", required_input_role="product_reference",
				value_type="File Path", required=1, allow_multiple=0, accepted_media_type="Image"),
		])

		self.assertEqual(
			["ASTV-1", "ASTV-2"],
			[
				row["asset_version"]
				for row in workflow_profiles.references_for_workflow(
					workflow,
					[{"asset_version": "ASTV-1"}, {"asset_version": "ASTV-2"}],
				)
			],
		)

	def test_optional_and_multiple_inputs_follow_declared_cardinality(self):
		self.assertIs(_SKIP_BINDING, _resolve_input_value("last frame", {}, required=False))
		self.assertEqual(
			["one.png", "two.png"],
			_resolve_input_value("product reference", {"product_reference": ["one.png", "two.png"]},
				value_type="File Paths", allow_multiple=True),
		)
		with self.assertRaises(frappe.ValidationError):
			_resolve_input_value("product reference", {"product_reference": ["one.png"]}, role_slot=1)

	def test_generic_execution_builder_uses_bindings_and_specification(self):
		workflow_version = frappe._dict(
			name="WF-TEST", adapter_key="comfyui_generic",
			workflow_json=json.dumps({
				"load": {"class_type": "LoadImage", "inputs": {"image": ""}},
				"prompt": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "seed": 0}},
				"save": {"class_type": "SaveImage", "inputs": {"filename_prefix": ""}},
			}),
			execution_spec=json.dumps({
				"parameters": [{"semantic": "seed", "node_key": "prompt", "input_name": "seed"}],
				"outputs": {"primary": {"node_key": "save", "media_type": "Image"}},
			}),
			bindings=[
				frappe._dict(binding_key="generation_prompt", node_key="prompt", input_name="text",
					required_input_role="", value_type="Text", required=1, allow_multiple=0),
				frappe._dict(binding_key="first_frame", node_key="load", input_name="image",
					required_input_role="first_frame", value_type="File Path", required=1, allow_multiple=0),
			],
		)
		workflow = build_execution_workflow(
			workflow_version, inputs={"generation_prompt": "hello", "first_frame": "input.png"},
			seed=9, width=1280, height=720, fps=24, frame_count=1, output_prefix="test",
		)
		self.assertEqual("hello", workflow["prompt"]["inputs"]["text"])
		self.assertEqual("input.png", workflow["load"]["inputs"]["image"])
		self.assertEqual(9, workflow["prompt"]["inputs"]["seed"])

	def test_invalid_binding_and_graph_are_rejected(self):
		workflow = frappe._dict(
			name="WFV-00004", workflow_json='{"node":{"class_type":"LoadImage","inputs":{"image":""}}}',
			bindings=[frappe._dict(binding_key="first_frame", node_key="missing", input_name="image",
				required_input_role="first_frame", value_type="File Path", required=1, allow_multiple=0)],
		)
		with self.assertRaises(frappe.ValidationError):
			validate_workflow_bindings(workflow)
		workflow.workflow_json = '{"load":{"inputs":{"image":""}}}'
		with self.assertRaises(frappe.ValidationError):
			validate_workflow_for_execution(workflow)
