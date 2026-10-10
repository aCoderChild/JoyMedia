from frappe.tests.utils import FrappeTestCase
import frappe
import json
from types import SimpleNamespace

from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter


class TestGenericComfyUIAdapter(FrappeTestCase):
	def test_workflows_without_optional_reference_conditioning_validate(self):
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = {
			"outputs": {"primary": {"media_type": "Video", "node_key": "save"}},
			"metadata": {"frame_count": 124, "produces_video": True},
		}
		adapter.validate_specification({"save": {"class_type": "SaveVideo", "inputs": {}}})

	def test_aspect_ratio_option_uses_delivery_dimensions(self):
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = {
			"parameters": [{
				"semantic": "aspect_ratio",
				"transform": "aspect_ratio_option",
				"options": {"16:9 (Widescreen)": 16 / 9, "1:1 (Square)": 1},
				"node_key": "resolution",
				"input_name": "aspect_ratio",
			}],
		}
		workflow = {"resolution": {"inputs": {"aspect_ratio": ""}}}

		result = adapter.prepare_execution(
			workflow,
			seed=123,
			width=1920,
			height=1080,
			frame_count=120,
			output_prefix="test",
			last_frame_index=119,
			last_frame_prefix="test_last",
		)

		self.assertEqual("16:9 (Widescreen)", result["resolution"]["inputs"]["aspect_ratio"])

	def test_aspect_ratio_dimension_transforms_keep_rectangular_resolution(self):
		adapter = GenericComfyUIAdapter()
		options = [
			{"width": 1344, "height": 768},
			{"width": 1024, "height": 1024},
		]
		adapter.execution_spec = {
			"parameters": [
				{
					"semantic": "width",
					"transform": "nearest_size_dimension",
					"dimension": "width",
					"options": options,
					"node_key": "size",
					"input_name": "width",
				},
				{
					"semantic": "height",
					"transform": "nearest_size_dimension",
					"dimension": "height",
					"options": options,
					"node_key": "size",
					"input_name": "height",
				},
			],
		}
		workflow = {"size": {"inputs": {"width": 0, "height": 0}}}

		result = adapter.prepare_execution(
			workflow,
			seed=123,
			width=1920,
			height=1080,
			frame_count=120,
			output_prefix="test",
			last_frame_index=119,
			last_frame_prefix="test_last",
		)

		self.assertEqual({"width": 1344, "height": 768}, result["size"]["inputs"])

	def test_flux2_optional_reference_roles_are_independent_and_prompt_only_is_valid(self):
		workflow = frappe.db.get_value(
			"Generation Workflow", {"workflow_key": "flux2_klein_multireference_keyframe"},
			["workflow_json", "execution_spec"], as_dict=True,
		)
		self.assertTrue(workflow, "Import a multi-reference workflow before running this integration test")
		graph = json.loads(workflow.workflow_json)
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = json.loads(workflow.execution_spec)
		adapter.validate_specification(graph)

		no_reference_graph = json.loads(json.dumps(graph))
		adapter.finalize_workflow(no_reference_graph, None, {})
		for node_key in (
			"person_image", "person_scale", "person_encode", "person_positive", "person_negative",
			"product_image", "product_scale", "product_encode", "product_positive", "product_negative",
			"environment_image", "environment_scale", "environment_encode",
			"environment_positive", "environment_negative",
		):
			self.assertNotIn(node_key, no_reference_graph)
		self.assertEqual(["positive_text", 0], no_reference_graph["guider"]["inputs"]["positive"])
		self.assertEqual(["negative_text", 0], no_reference_graph["guider"]["inputs"]["negative"])

		partial_graph = json.loads(json.dumps(graph))
		adapter.finalize_workflow(partial_graph, None, {
			"person": "/input/person.png",
			"environment": "/input/environment.png",
		})
		self.assertNotIn("product_image", partial_graph)
		self.assertEqual(["person_positive", 0], partial_graph["environment_positive"]["inputs"]["conditioning"])
		self.assertEqual(["person_negative", 0], partial_graph["environment_negative"]["inputs"]["conditioning"])
		self.assertEqual(["environment_positive", 0], partial_graph["guider"]["inputs"]["positive"])

	def test_single_file_path_binding_scalarizes_staged_list_generically(self):
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = {}
		workflow = {"person_image": {"inputs": {"image": "person_reference"}}}
		version = SimpleNamespace(bindings=[SimpleNamespace(
			required_input_role="person", value_type="File Paths", allow_multiple=0,
			node_key="person_image", input_name="image",
		)])

		adapter.finalize_workflow(workflow, version, {"person": ["comfy/input/person.png"]})

		self.assertEqual("comfy/input/person.png", workflow["person_image"]["inputs"]["image"])

	def test_multiple_file_path_binding_preserves_list_contract(self):
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = {}
		workflow = {"references": {"inputs": {"images": []}}}
		version = SimpleNamespace(bindings=[SimpleNamespace(
			required_input_role="references", value_type="File Paths", allow_multiple=1,
			node_key="references", input_name="images",
		)])

		adapter.finalize_workflow(workflow, version, {"references": ["a.png", "b.png"]})

		self.assertEqual([], workflow["references"]["inputs"]["images"])

	def test_flux2_reference_roles_normalize_common_annotations(self):
		from joymedia.services.reference_compositor import normalize_reference_role
		self.assertEqual("person", normalize_reference_role("People"))
		self.assertEqual("environment", normalize_reference_role("background"))
