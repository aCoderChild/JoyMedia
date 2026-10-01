from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflow_resolver import (
	_SKIP_BINDING,
	_resolve_generation_input,
	validate_workflow_bindings,
	validate_workflow_for_execution,
)
from joymedia.workflow_adapters.minimax_h3 import MiniMaxH3WorkflowAdapter


class TestWorkflowResolver(FrappeTestCase):
	def test_human_readable_required_role_resolves_canonical_staged_input(self):
		job = frappe._dict(name="JOB-00001")

		value = _resolve_generation_input(
			job,
			"FIRST FRAME",
			{"first_frame": "first.png"},
		)

		self.assertEqual("first.png", value)

	def test_optional_last_frame_is_skipped_when_not_staged(self):
		job = frappe._dict(name="JOB-00001")

		value = _resolve_generation_input(
			job,
			"LAST FRAME",
			{},
			required=False,
		)

		self.assertIs(value, _SKIP_BINDING)

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
