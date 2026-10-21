"""The upstream base sampler needs both reference-conditioned CFG branches."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.patches.register_flux2_klein_base_pipeline import register_image
from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS
from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter


class TestFlux2KleinBase(FrappeTestCase):
	def inputs(self):
		return (
			json.loads((GRAPHS / "flux2_klein_base_keyframe.json").read_text()),
			json.loads((GRAPHS / "flux2_klein_base_keyframe.execution.json").read_text()),
		)

	def test_graph_contract_and_both_cfg_branches_keep_the_same_physical_references(self):
		graph, spec = self.inputs()
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = spec
		adapter.validate_specification(graph)
		adapter._finalize_optional_input_chains(
			graph,
			spec["input_preprocessing"],
			{
				"character": ["actor.png"],
				"product": ["product.png"],
				"environment": ["room.png"],
			},
		)
		self.assertEqual(["environment_ref", 0], graph["guider"]["inputs"]["positive"])
		self.assertEqual(["environment_negative_ref", 0], graph["guider"]["inputs"]["negative"])
		self.assertEqual(["character1_ref", 0], graph["product_ref"]["inputs"]["conditioning"])
		self.assertEqual(
			["character1_negative_ref", 0], graph["product_negative_ref"]["inputs"]["conditioning"]
		)
		self.assertEqual(
			graph["product_ref"]["inputs"]["latent"], graph["product_negative_ref"]["inputs"]["latent"]
		)
		for prefix in ["character2", "character3", "person", "general"]:
			self.assertFalse(any(key.startswith(prefix + "_") for key in graph))
		for node in graph.values():
			for value in node["inputs"].values():
				if isinstance(value, list) and len(value) == 2:
					self.assertIn(value[0], graph)

	def test_no_reference_leaves_valid_unconditioned_negative_text(self):
		graph, spec = self.inputs()
		GenericComfyUIAdapter._finalize_optional_input_chains(graph, spec["input_preprocessing"], {})
		self.assertEqual(["text", 0], graph["guider"]["inputs"]["positive"])
		self.assertEqual(["negative_text", 0], graph["guider"]["inputs"]["negative"])
		self.assertFalse(any(node["class_type"] == "ReferenceLatent" for node in graph.values()))

	def test_registration_is_idempotent_without_changing_the_active_profile(self):
		from joymedia.services.workflows.pipeline import get_active_generation_pipeline

		previous = get_active_generation_pipeline().name
		name = register_image()
		self.assertEqual(name, register_image())
		self.assertEqual(previous, get_active_generation_pipeline().name)
		workflow = frappe.get_doc("Generation Workflow", name)
		self.assertEqual("comfyui_generic", workflow.adapter_key)
