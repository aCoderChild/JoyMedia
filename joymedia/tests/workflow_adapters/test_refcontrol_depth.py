"""The adapted upstream depth workflow must never invent its layout input."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.patches.register_refcontrol_depth_pipeline import GRAPH, SPEC, register_image
from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter


class TestRefControlDepth(FrappeTestCase):
	def test_upstream_control_precedes_identity_and_conditions_both_cfg_branches(self):
		graph, spec = json.loads(GRAPH.read_text()), json.loads(SPEC.read_text())
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = spec
		adapter.validate_specification(graph)
		adapter._finalize_optional_input_chains(
			graph,
			spec["input_preprocessing"],
			{"character": ["mascot.png"], "product": ["pack.png"]},
		)
		self.assertEqual(["refcontrol_lora", 0], graph["guider"]["inputs"]["model"])
		self.assertEqual(["product_ref", 0], graph["guider"]["inputs"]["positive"])
		self.assertEqual(["product_negative_ref", 0], graph["guider"]["inputs"]["negative"])
		self.assertEqual(["geometry_positive_ref", 0], graph["character1_ref"]["inputs"]["conditioning"])
		self.assertEqual(
			["geometry_negative_ref", 0], graph["character1_negative_ref"]["inputs"]["conditioning"]
		)
		self.assertEqual(["geometry_encode", 0], graph["geometry_positive_ref"]["inputs"]["latent"])

	def test_registration_requires_a_separate_layout_reference_and_does_not_promote(self):
		from joymedia.services.workflows.pipeline import get_active_generation_pipeline

		previous = get_active_generation_pipeline().name
		name = register_image()
		self.assertEqual(name, register_image())
		self.assertEqual(previous, get_active_generation_pipeline().name)
		workflow = frappe.get_doc("Generation Workflow", name)
		geometry = next(row for row in workflow.bindings if row.required_input_role == "geometry_reference")
		self.assertTrue(geometry.required)
		self.assertEqual("geometry_image", geometry.node_key)

	def test_execute_registers_a_sibling_pipeline_without_promoting_it(self):
		from types import SimpleNamespace
		from unittest.mock import patch

		from joymedia.patches import register_refcontrol_depth_pipeline as registration

		image = "WF-DEPTH"
		video = "WF-VIDEO"
		created = SimpleNamespace(name="PIPE-DEPTH")
		with (
			patch.object(registration, "register_image", return_value=image),
			patch.object(registration, "_pipeline_with", return_value=None),
			patch.object(frappe.db, "get_value", return_value="Video"),
			patch.object(frappe, "get_doc", return_value=SimpleNamespace(insert=lambda **kwargs: created)),
		):
			result = registration.execute(video)
		self.assertEqual({"pipeline": "PIPE-DEPTH", "image_workflow": image, "video_workflow": video}, result)
