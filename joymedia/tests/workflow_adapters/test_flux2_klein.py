import copy
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.patches.register_flux2_klein_pipeline import GRAPH, keyframe_spec
from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter


class TestFlux2KleinKeyframe(FrappeTestCase):
	def _adapter(self):
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = keyframe_spec()
		return adapter

	def test_the_shipped_graph_satisfies_its_specification(self):
		self._adapter().validate_specification(json.loads(GRAPH.read_text()))

	def test_each_character_is_its_own_reference_in_order_and_absent_slots_leave_no_nodes(self):
		graph = copy.deepcopy(json.loads(GRAPH.read_text()))
		spec = keyframe_spec()
		GenericComfyUIAdapter._finalize_optional_input_chains(
			graph,
			spec["input_preprocessing"],
			{"character": ["mother.png", "kid.png"], "environment": ["room.png"]},
		)
		self.assertEqual(["environment_ref", 0], graph["guider"]["inputs"]["conditioning"])
		self.assertEqual(["character2_ref", 0], graph["environment_ref"]["inputs"]["conditioning"])
		self.assertEqual(["character1_ref", 0], graph["character2_ref"]["inputs"]["conditioning"])
		self.assertEqual(["text", 0], graph["character1_ref"]["inputs"]["conditioning"])
		for prefix in ("character3", "person", "product", "general"):
			self.assertFalse([key for key in graph if key.startswith(f"{prefix}_")], prefix)

	def test_composition_reference_is_conditioning_without_becoming_an_extra_actor(self):
		graph = copy.deepcopy(json.loads(GRAPH.read_text()))
		GenericComfyUIAdapter._finalize_optional_input_chains(
			graph,
			keyframe_spec()["input_preprocessing"],
			{"product": ["product.png"], "general": ["contact-view.png"]},
		)
		self.assertEqual(["general_ref", 0], graph["guider"]["inputs"]["conditioning"])
		self.assertEqual(["product_ref", 0], graph["general_ref"]["inputs"]["conditioning"])
		self.assertFalse(any(key.startswith("character") for key in graph))

	def test_without_references_the_prompt_alone_conditions_the_image(self):
		graph = copy.deepcopy(json.loads(GRAPH.read_text()))
		GenericComfyUIAdapter._finalize_optional_input_chains(
			graph, keyframe_spec()["input_preprocessing"], {}
		)
		self.assertEqual(["text", 0], graph["guider"]["inputs"]["conditioning"])
