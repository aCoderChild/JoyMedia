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
		if not workflow:
			self.skipTest("Flux 2 multi-reference workflow is not installed in this site")
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

	def test_flux2_expanded_workflow_accepts_second_product_and_reference_board(self):
		from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow
		from joymedia.services.workflow_resolver import build_execution_workflow

		workflow = get_latest_valid_workflow("flux2_klein_multireference_keyframe")
		if not workflow:
			self.skipTest("Flux 2 multi-reference workflow is not installed in this site")
		roles = {binding.required_input_role for binding in workflow.bindings}
		self.assertTrue({"product_2", "reference_board"}.issubset(roles))
		resolved = build_execution_workflow(
			workflow,
			inputs={
				"generation_prompt": "A presenter markets both products clearly.",
				"person": ["person.png"], "product": ["product-a.png"],
				"product_2": ["product-b.png"],
				"reference_board": ["overflow-board.png"],
			},
			seed=1, width=1344, height=768, fps=24, frame_count=1, output_prefix="test",
		)
		self.assertEqual("product-b.png", resolved["product_2_image"]["inputs"]["image"])
		self.assertEqual("overflow-board.png", resolved["reference_board_image"]["inputs"]["image"])
		self.assertEqual(["reference_board_positive", 0], resolved["guider"]["inputs"]["positive"])


class TestOptionalInputChains(FrappeTestCase):
	def _graph(self):
		return {
			"base": {"class_type": "Base", "inputs": {}},
			"a": {"class_type": "Link", "inputs": {"in": None}},
			"b": {"class_type": "Link", "inputs": {"in": None}},
			"a_aux": {"class_type": "Aux", "inputs": {}},
			"target": {"class_type": "Target", "inputs": {"x": None}},
		}

	def _adapter(self):
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = {"input_preprocessing": {"optional_input_chains": [{
			"target": {"node_key": "target", "input_name": "x"}, "base": ["base", 0],
			"links": [
				{"role": "a", "nodes": ["a", "a_aux"], "node": "a", "input": "in"},
				{"role": "b", "nodes": ["b"], "node": "b", "input": "in"},
			],
		}]}}
		return adapter

	def test_present_links_chain_in_order_and_absent_nodes_are_removed(self):
		workflow = self._graph()
		adapter = self._adapter()
		adapter._finalize_optional_input_chains(
			workflow, adapter.execution_spec["input_preprocessing"], {"a": ["f"], "b": ["g"]}
		)
		self.assertEqual(["base", 0], workflow["a"]["inputs"]["in"])
		self.assertEqual(["a", 0], workflow["b"]["inputs"]["in"])
		self.assertEqual(["b", 0], workflow["target"]["inputs"]["x"])

	def test_with_no_references_target_reads_the_base(self):
		workflow = self._graph()
		adapter = self._adapter()
		adapter._finalize_optional_input_chains(workflow, adapter.execution_spec["input_preprocessing"], {})
		self.assertEqual(["base", 0], workflow["target"]["inputs"]["x"])
		self.assertEqual({"base", "target"}, set(workflow))

	def test_skipping_a_middle_link_keeps_the_chain_connected(self):
		workflow = self._graph()
		adapter = self._adapter()
		adapter._finalize_optional_input_chains(workflow, adapter.execution_spec["input_preprocessing"], {"b": ["g"]})
		self.assertEqual(["base", 0], workflow["b"]["inputs"]["in"])
		self.assertNotIn("a", workflow)

	def test_specification_rejects_links_to_unknown_nodes(self):
		adapter = self._adapter()
		workflow = self._graph()
		del workflow["a_aux"]
		with self.assertRaises(ValueError):
			adapter._validate_input_chain(workflow, adapter.execution_spec["input_preprocessing"]["optional_input_chains"][0])


class TestShippedKeyframeWorkflow(FrappeTestCase):
	def _adapter_and_graph(self):
		from pathlib import Path

		from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPH, _keyframe_spec

		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = _keyframe_spec()
		return adapter, json.loads(Path(GRAPH).read_text())

	def test_the_shipped_graph_satisfies_its_specification(self):
		adapter, graph = self._adapter_and_graph()
		adapter.validate_specification(graph)

	def test_one_character_image_feeds_both_identity_paths(self):
		_adapter, graph = self._adapter_and_graph()
		# PuLID reads node 54; the Redux encoder must read the same node, not a separate placeholder.
		self.assertEqual(["54", 0], graph["62"]["inputs"]["image"])
		self.assertEqual(["54", 0], graph["character_encode"]["inputs"]["image"])
		self.assertNotIn("character_image", graph)

	def test_a_character_alone_leaves_a_complete_graph(self):
		adapter, graph = self._adapter_and_graph()
		adapter._finalize_optional_input_chains(graph, adapter.execution_spec["input_preprocessing"], {"person": ["x.png"]})
		self.assertEqual(["product_redux" if "product_redux" in graph else "character_redux", 0], graph["47"]["inputs"]["conditioning"])
		self.assertNotIn("product_image", graph)
		self.assertEqual(["character_redux", 0], graph["47"]["inputs"]["conditioning"])
