import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflow_resolver import resolve_attempt


class TestWorkflowResolutionExecution(FrappeTestCase):
	def test_resolve_attempt_uses_generation_workflow_metadata_for_adapter(self):
		attempt = MagicMock()
		attempt.name = "ATT-00001"
		attempt.generation_task = "JOB-00001"
		attempt.seed = 424242

		job = MagicMock()
		job.name = "JOB-00001"
		job.generation_run = "RUN-00001"
		job.workflow = "WF-00001"
		job.prompt_text = "A cinematic product shot."
		job.segment_frame_count = 120

		run = MagicMock()
		run.name = "RUN-00001"
		run.project_snapshot_json = json.dumps({
			"delivery_width": 1280,
			"delivery_height": 720,
		})

		workflow_graph = {
			"114": {
				"class_type": "LoadImage",
				"inputs": {"image": "placeholder.png"},
			},
			"105:104": {
				"class_type": "MiniMaxH3ImageToVideo",
				"inputs": {
					"prompt": "placeholder",
					"width": 1280,
					"height": 720,
				},
			},
		}
		workflow_version = frappe._dict(
			name="WF-00001",
			adapter_key="minimax_h3_i2v",
			workflow_json=json.dumps(workflow_graph),
			bindings=[
				frappe._dict(
					binding_key="generation_prompt",
					node_key="105:104",
					input_name="prompt",
					required_input_role="",
					value_type="Text",
					required=1,
					accepted_media_type="Any",
					allow_multiple=0,
				),
				frappe._dict(
					binding_key="first_frame",
					node_key="114",
					input_name="image",
					required_input_role="first_frame",
					value_type="File Path",
					required=1,
					accepted_media_type="Image",
					allow_multiple=0,
				),
			],
		)

		docs = {
			"Generation Attempt": attempt,
			"Generation Task": job,
			"Generation Run": run,
			"Generation Workflow": workflow_version,
		}

		adapter = MagicMock()
		with patch(
			"joymedia.services.workflow_resolver.frappe.get_doc",
			side_effect=lambda doctype, name: docs[doctype],
		), patch(
			"joymedia.services.workflow_resolver.get_workflow_adapter",
			return_value=adapter,
		) as get_adapter:
			resolved = resolve_attempt(
				attempt.name,
				staged_inputs={"first_frame": ["ComfyUI/input/product.png"]},
			)

		get_adapter.assert_called_once_with(workflow_version)
		self.assertEqual(
			"ComfyUI/input/product.png",
			resolved["114"]["inputs"]["image"],
		)
		self.assertEqual(
			"A cinematic product shot.",
			resolved["105:104"]["inputs"]["prompt"],
		)
		adapter.prepare_execution.assert_called_once()
		attempt.save.assert_called_once_with(ignore_permissions=True)
