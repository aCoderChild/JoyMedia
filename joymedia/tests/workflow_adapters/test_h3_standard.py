"""The H3 video stage resolves to exactly what Input-standards-H3 specifies."""

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.patches.register_h3_standard_pipeline import register_video
from joymedia.services.planning.h3 import LAYERS, five_layers, unheld_product
from joymedia.services.workflows.resolver import build_execution_workflow


class TestH3Standard(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.workflow = frappe.get_doc("Generation Workflow", register_video())

	def graph(self, width=720, height=1280, **inputs):
		return build_execution_workflow(
			self.workflow,
			inputs={
				"generation_prompt": "Camera Direction: Static.",
				"first_frame": ["opening.png"],
				**inputs,
			},
			seed=42,
			width=width,
			height=height,
			fps=24,
			frame_count=124,
			output_prefix="h3-standard",
		)

	def test_models_sampler_and_output_follow_the_standard(self):
		graph = self.graph()
		self.assertEqual(
			"minimax_h3_fl2va_pruned_int8_convrot.safetensors", graph["6"]["inputs"]["unet_name"]
		)
		lora = graph["121"]["inputs"]
		self.assertEqual(
			("minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", 1.0),
			(lora["lora_name"], lora["strength_model"]),
		)
		self.assertEqual(["121", 0], graph["sigma_shift"]["inputs"]["model"])
		self.assertEqual(
			(12.0, 3.0),
			(graph["sigma_shift"]["inputs"]["shift_video"], graph["sigma_shift"]["inputs"]["shift_audio"]),
		)
		self.assertEqual("minimax", graph["13"]["inputs"]["type"])
		sampler = graph["sampler"]["inputs"]
		self.assertEqual(
			(8, 1.0, "euler", "simple", 1.0, 42),
			(
				sampler["steps"],
				sampler["cfg"],
				sampler["sampler_name"],
				sampler["scheduler"],
				sampler["denoise"],
				sampler["seed"],
			),
		)
		output = graph["92"]["inputs"]
		self.assertEqual(
			("video/h264-mp4", 18, 24.0), (output["format"], output["crf"], output["frame_rate"])
		)
		self.assertEqual(["23", 0], output["audio"])

	def test_native_size_comes_from_the_aspect_not_the_delivery_pixels(self):
		for (width, height), native in [((720, 1280), (768, 1344)), ((1920, 1080), (1344, 768))]:
			graph = self.graph(width, height)
			self.assertEqual(native, (graph["104"]["inputs"]["width"], graph["104"]["inputs"]["height"]))
			scale = graph["first_frame_size"]["inputs"]
			self.assertEqual(
				(*native, "lanczos", "center"),
				(scale["width"], scale["height"], scale["upscale_method"], scale["crop"]),
			)
			self.assertEqual(["first_frame_size", 0], graph["104"]["inputs"]["first_frame"])

	def test_other_delivery_ratios_keep_their_shape(self):
		for (width, height), size in [((1080, 1080), (1088, 1088)), ((1080, 1350), (1088, 1344))]:
			graph = self.graph(width, height)
			self.assertEqual(size, (graph["104"]["inputs"]["width"], graph["104"]["inputs"]["height"]))

	def test_last_frame_is_scaled_the_same_way_and_only_when_supplied(self):
		# Like the existing I2V graph, an absent last frame leaves its loader disconnected,
		# so ComfyUI never executes it.
		self.assertIsNone(self.graph()["104"]["inputs"]["last_frame"])
		graph = self.graph(last_frame=["endpoint.png"])
		self.assertEqual("endpoint.png", graph["115"]["inputs"]["image"])
		self.assertEqual(["last_frame_size", 0], graph["104"]["inputs"]["last_frame"])

	def test_prompt_is_five_ordered_layers(self):
		prompt = five_layers(
			["Static."], ["The bear."], ["It lifts the pack.."], ["Warm light."], ["A rustle."]
		)
		self.assertEqual(
			[f"{label}:" for label in LAYERS],
			[line.split(":")[0] + ":" for line in prompt.split("\n\n")],
		)
		self.assertIn("It lifts the pack.", prompt)
		self.assertNotIn("..", prompt)

	def test_a_product_only_scene_forbids_hands(self):
		self.assertIn("no hands", unheld_product({"references": [{"reference_role": "product"}]}))
		self.assertEqual(
			"",
			unheld_product({"references": [{"reference_role": "product"}, {"reference_role": "character"}]}),
		)


class TestH3Ref2VAStandard(FrappeTestCase):
	def setUp(self):
		super().setUp()
		from joymedia.patches.register_h3_ref2va_standard_pipeline import register_video as register_ref2va

		self.workflow = frappe.get_doc("Generation Workflow", register_ref2va())

	def graph(self, **inputs):
		return build_execution_workflow(
			self.workflow,
			inputs={
				"generation_prompt": "Camera Direction: Static.",
				"first_frame": ["opening.png"],
				**inputs,
			},
			seed=7,
			width=720,
			height=1280,
			fps=24,
			frame_count=124,
			output_prefix="r2v-standard",
		)

	def test_product_and_mascot_are_references_at_native_size(self):
		graph = self.graph(product=["pack.png"], character=["mascot.png"])
		self.assertEqual(
			"minimax_h3_ref2va_pruned_int8_convrot.safetensors", graph["6"]["inputs"]["unet_name"]
		)
		node = graph["104"]["inputs"]
		self.assertEqual((768, 1344), (node["width"], node["height"]))
		self.assertEqual(["opening_size", 0], node["ref_images.ref_image_0"])
		self.assertEqual(["opening_size", 0], graph["guide_first"]["inputs"]["image"])
		self.assertEqual(
			(["product", 0], ["character", 0]),
			(node["ref_images.ref_image_1"], node["ref_images.ref_image_2"]),
		)
		self.assertEqual(("simple", 20), (graph["9"]["inputs"]["scheduler"], graph["9"]["inputs"]["steps"]))
		self.assertEqual(
			(12.0, 3.0),
			(graph["sigma_shift"]["inputs"]["shift_video"], graph["sigma_shift"]["inputs"]["shift_audio"]),
		)
		self.assertEqual(
			("video/h264-mp4", 18), (graph["92"]["inputs"]["format"], graph["92"]["inputs"]["crf"])
		)
		# The roles are part of the five-layer prompt, not appended after it.
		self.assertEqual("Camera Direction: Static.", node["prompt"])

	def test_absent_closing_frame_leaves_no_nodes(self):
		graph = self.graph()
		for key in ("115", "closing_size", "guide_last"):
			self.assertNotIn(key, graph)


class TestH3StandardDelivery(FrappeTestCase):
	def test_both_standard_stages_deliver_2k_and_fit_the_whole_clip(self):
		from joymedia.patches.register_h3_ref2va_standard_pipeline import register_video as ref2va
		from joymedia.services.editing.delivery import delivery_contract

		for name in (register_video(), ref2va()):
			contract = delivery_contract(
				frappe.get_doc("Generation Workflow", name), {"width": 720, "height": 1280}
			)
			self.assertEqual(
				(1440, 2560, "preserve_endpoints"),
				(contract["width"], contract["height"], contract["temporal_fit"]),
			)
