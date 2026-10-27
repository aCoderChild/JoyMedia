"""Contract checks for the opt-in upstream pose-control adapter."""

import json
from io import BytesIO

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image, ImageDraw

from joymedia.patches.register_refcontrol_pose_pipeline import GRAPH, SPEC, register_image
from joymedia.services.planning.pose_assets import _retains_body_proportions
from joymedia.services.planning.pose_guides import _validated_keypoints
from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter


class TestRefControlPose(FrappeTestCase):
	def test_skeleton_precedes_identity_and_conditions_both_branches(self):
		graph, spec = json.loads(GRAPH.read_text()), json.loads(SPEC.read_text())
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = spec
		adapter.validate_specification(graph)
		adapter._finalize_optional_input_chains(
			graph, spec["input_preprocessing"], {"character": ["shera.png"]}
		)
		self.assertNotIn("geometry_depth", graph)
		self.assertEqual(["geometry_image", 0], graph["geometry_scale"]["inputs"]["image"])
		self.assertEqual(["geometry_positive_ref", 0], graph["character1_ref"]["inputs"]["conditioning"])
		self.assertEqual(
			["geometry_negative_ref", 0], graph["character1_negative_ref"]["inputs"]["conditioning"]
		)
		self.assertEqual(
			"refcontrol-pose-klein-4b.safetensors", graph["refcontrol_lora"]["inputs"]["lora_name"]
		)

	def test_registration_is_opt_in_and_requires_guide(self):
		from joymedia.services.workflows.pipeline import get_active_generation_pipeline

		previous = get_active_generation_pipeline().name
		name = register_image()
		self.assertEqual(name, register_image())
		self.assertEqual(previous, get_active_generation_pipeline().name)
		workflow = frappe.get_doc("Generation Workflow", name)
		guide = next(row for row in workflow.bindings if row.required_input_role == "pose_guide")
		self.assertTrue(guide.required)

	def test_invalid_guide_is_rejected(self):
		with self.assertRaises(ValueError):
			_validated_keypoints([[0.5, 0.5, 1]] * 17)
		with self.assertRaises(ValueError):
			_validated_keypoints([[0.5, 0.5, 1]] * 8 + [[float("nan"), 0.5, 1]] + [[0.5, 0.5, 1]] * 9)

	def test_rounded_mascot_must_not_become_human_proportioned(self):
		def figure(box):
			canvas = Image.new("RGB", (512, 512), "white")
			ImageDraw.Draw(canvas).ellipse(box, fill=(150, 120, 100))
			buffer = BytesIO()
			canvas.save(buffer, format="PNG")
			return buffer.getvalue()

		source = figure((70, 75, 440, 450))
		self.assertTrue(_retains_body_proportions(source, figure((80, 60, 430, 460))))
		self.assertFalse(_retains_body_proportions(source, figure((195, 35, 320, 480))))
