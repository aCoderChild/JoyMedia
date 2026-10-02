from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflow_resolver import (
	_SKIP_BINDING,
	_resolve_semantic_binding,
	_resolve_generation_input,
	get_workflow_input_contract,
	validate_workflow_bindings,
	validate_workflow_for_execution,
)
from joymedia.workflow_adapters.minimax_h3 import MiniMaxH3WorkflowAdapter
from joymedia.workflow_adapters.minimax_h3_profiles import (
	MiniMaxH3ImageToVideoAdapter,
	MiniMaxH3ReferenceToVideoAdapter,
)


class TestWorkflowResolver(FrappeTestCase):
	def test_human_readable_required_role_resolves_canonical_staged_input(self):
		job = frappe._dict(name="JOB-00001")

		value = _resolve_generation_input(
			job,
			"FIRST FRAME",
			{"first_frame": "first.png"},
		)

		self.assertEqual("first.png", value)

	def test_ordered_r2v_reference_bindings_use_product_reference_order(self):
		workflow = frappe._dict(
			bindings=[
				frappe._dict(
					binding_key="reference_image_1",
					required_input_role="product_reference",
					value_type="File Path",
					required=1,
				),
				frappe._dict(
					binding_key="reference_image_2",
					required_input_role="product_reference",
					value_type="File Path",
					required=0,
				),
			]
		)

		contract = get_workflow_input_contract(workflow)
		self.assertTrue(contract[0]["allow_multiple"])
		job = frappe._dict(name="JOB-00001", prompt_text="prompt")
		self.assertEqual(
			"one.png",
			_resolve_semantic_binding(
				workflow.bindings[0], job, {"product_reference": ["one.png", "two.png"]}
			),
		)
		self.assertEqual(
			"two.png",
			_resolve_semantic_binding(
				workflow.bindings[1], job, {"product_reference": ["one.png", "two.png"]}
			),
		)

	def test_optional_last_frame_is_skipped_when_not_staged(self):
		job = frappe._dict(name="JOB-00001")

		value = _resolve_generation_input(
			job,
			"LAST FRAME",
			{},
			required=False,
		)

		self.assertIs(value, _SKIP_BINDING)

	def test_file_paths_binding_preserves_repeated_role_inputs(self):
		job = frappe._dict(name="JOB-00001")

		value = _resolve_generation_input(
			job,
			"PRODUCT REFERENCE",
			{"product_reference": ["one.png", "two.png"]},
			value_type="File Paths",
		)

		self.assertEqual(["one.png", "two.png"], value)

	def test_file_path_binding_rejects_repeated_role_inputs(self):
		job = frappe._dict(name="JOB-00001")

		with self.assertRaises(frappe.ValidationError):
			_resolve_generation_input(
				job,
				"PRODUCT REFERENCE",
				{"product_reference": ["one.png", "two.png"]},
				value_type="File Path",
			)

	def test_h3_optional_last_frame_removes_stale_conditioning_branch(self):
		workflow = {
			"1": {"inputs": {"image": "ComfyUI/input/2.png"}},
			"2": {"inputs": {"image": ["1", 0]}},
			"minimax_cond": {"inputs": {"last_frame": ["2", 0]}},
			"save_last_frame": {"inputs": {"images": ["last_frame", 0]}},
		}
		workflow_version = frappe._dict(
			bindings=[frappe._dict(binding_key="last_frame", node_key="1")]
		)

		MiniMaxH3WorkflowAdapter().finalize_workflow(workflow, workflow_version, {})

		self.assertNotIn("1", workflow)
		self.assertNotIn("2", workflow)
		self.assertIsNone(workflow["minimax_cond"]["inputs"]["last_frame"])
		self.assertIn("save_last_frame", workflow)

	def test_h3_last_frame_branch_is_preserved_when_staged(self):
		workflow = {
			"1": {"inputs": {"image": "ComfyUI/input/2.png"}},
			"2": {"inputs": {"image": ["1", 0]}},
			"minimax_cond": {"inputs": {"last_frame": ["2", 0]}},
		}
		workflow_version = frappe._dict(
			bindings=[frappe._dict(binding_key="last_frame", node_key="1")]
		)

		MiniMaxH3WorkflowAdapter().finalize_workflow(
			workflow,
			workflow_version,
			{"last_frame": "/tmp/last-frame.png"},
		)

		self.assertIn("1", workflow)
		self.assertEqual(["2", 0], workflow["minimax_cond"]["inputs"]["last_frame"])

	def test_invalid_binding_reports_workflow_node_and_input(self):
		workflow = frappe._dict(
			name="WFV-00004",
			workflow_json='{"minimax_cond":{"inputs":{"length":124}}}',
			bindings=[
				frappe._dict(
					binding_key="first_frame",
					node_key="load_img",
					input_name="image",
					required_input_role="first_frame",
				)
			],
		)

		with self.assertRaises(frappe.ValidationError) as context:
			validate_workflow_bindings(workflow)

		self.assertIn("WFV-00004", str(context.exception))
		self.assertIn("load_img", str(context.exception))
		self.assertIn("image", str(context.exception))

	def test_execution_validation_rejects_workflow_without_class_type(self):
		workflow = frappe._dict(
			name="WFV-00005",
			workflow_json='{"load_img":{"inputs":{"image":""}}}',
		)

		with self.assertRaises(frappe.ValidationError) as context:
			validate_workflow_for_execution(workflow)

		self.assertIn("missing class_type", str(context.exception))
		self.assertIn("load_img", str(context.exception))

	def test_execution_validation_rejects_incomplete_video_combine(self):
		workflow = frappe._dict(
			name="WFV-00006",
			workflow_json=(
				'{"save_video":{"class_type":"VHS_VideoCombine",'
				'"inputs":{"frame_rate":24}}}'
			),
		)

		with self.assertRaises(frappe.ValidationError) as context:
			validate_workflow_for_execution(workflow)

		message = str(context.exception)
		self.assertIn("VHS_VideoCombine", message)
		self.assertIn("filename_prefix", message)
		self.assertIn("images", message)

	def test_execution_validation_rejects_reference_to_missing_node(self):
		workflow = frappe._dict(
			name="WFV-00007",
			workflow_json=(
				'{"save_video":{"class_type":"VHS_VideoCombine",'
				'"inputs":{"images":["dec_video",0],"frame_rate":24,'
				'"loop_count":0,"filename_prefix":"JoyMedia",'
				'"format":"video/h264-mp4","pingpong":false,'
				'"save_output":true}}}'
			),
		)

		with self.assertRaises(frappe.ValidationError) as context:
			validate_workflow_for_execution(workflow)

		message = str(context.exception)
		self.assertIn("save_video.images", message)
		self.assertIn("dec_video", message)

	def test_h3_prepare_execution_injects_internal_execution_values(self):
		workflow = {
			"sampler": {"inputs": {"seed": 0}},
			"minimax_cond": {"inputs": {"length": 1, "width": 1, "height": 1}},
			"scale_img": {"inputs": {"width": 1, "height": 1}},
			"2": {"inputs": {"width": 1, "height": 1}},
			"save_video": {"inputs": {"filename_prefix": "old"}},
			"last_frame": {"inputs": {"batch_index": 0}},
			"save_last_frame": {"inputs": {"filename_prefix": "old"}},
		}

		MiniMaxH3WorkflowAdapter().prepare_execution(
			workflow,
			seed=94821731,
			width=1280,
			height=720,
			frame_count=120,
			output_prefix="JOB-1_ATT-1",
			last_frame_index=119,
			last_frame_prefix="JOB-1_ATT-1_last_frame",
		)

		self.assertEqual(94821731, workflow["sampler"]["inputs"]["seed"])
		self.assertEqual(120, workflow["minimax_cond"]["inputs"]["length"])
		self.assertEqual(1280, workflow["2"]["inputs"]["width"])
		self.assertEqual(720, workflow["scale_img"]["inputs"]["height"])
		self.assertEqual("JOB-1_ATT-1", workflow["save_video"]["inputs"]["filename_prefix"])
		self.assertEqual(119, workflow["last_frame"]["inputs"]["batch_index"])

	def test_h3_i2v_api_profile_patches_exported_node_keys(self):
		workflow = {
			"105:15": {"inputs": {"noise_seed": 0}},
			"105:111": {"inputs": {"value": 5}},
			"105:104": {"inputs": {"width": ["115", 0], "height": ["115", 1]}},
			"92": {"inputs": {"filename_prefix": "old"}},
		}

		MiniMaxH3ImageToVideoAdapter().prepare_execution(
			workflow,
			seed=94821731,
			width=1280,
			height=720,
			frame_count=120,
			output_prefix="JOB-1_ATT-1",
			last_frame_index=119,
			last_frame_prefix="unused",
		)

		self.assertEqual(94821731, workflow["105:15"]["inputs"]["noise_seed"])
		self.assertEqual(["115", 0], workflow["105:104"]["inputs"]["width"])
		self.assertEqual(["115", 1], workflow["105:104"]["inputs"]["height"])
		self.assertEqual("JOB-1_ATT-1", workflow["92"]["inputs"]["filename_prefix"])

	def test_h3_r2v_api_profile_patches_exported_node_keys(self):
		workflow = {
			"129": {"inputs": {"noise_seed": 0}},
			"132": {"inputs": {"value": 5}},
			"136": {"inputs": {"width": ["115", 0], "height": ["115", 1]}},
			"92": {"inputs": {"filename_prefix": "old"}},
		}

		MiniMaxH3ReferenceToVideoAdapter().prepare_execution(
			workflow,
			seed=94821731,
			width=1280,
			height=720,
			frame_count=120,
			output_prefix="JOB-1_ATT-1",
			last_frame_index=119,
			last_frame_prefix="unused",
		)

		self.assertEqual(94821731, workflow["129"]["inputs"]["noise_seed"])
		self.assertEqual(["115", 0], workflow["136"]["inputs"]["width"])
		self.assertEqual(["115", 1], workflow["136"]["inputs"]["height"])
		self.assertEqual("JOB-1_ATT-1", workflow["92"]["inputs"]["filename_prefix"])
