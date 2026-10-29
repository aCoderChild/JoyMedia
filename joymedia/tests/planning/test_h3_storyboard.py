import copy
import json
from unittest import TestCase

import frappe

from joymedia.patches.register_h3_storyboard_pipeline import image_recipe
from joymedia.services.planning.h3 import compile_opening_hold


class TestH3Storyboard(TestCase):
	def test_recipe_samples_a_fixed_preparation_clip_without_using_shot_duration(self):
		graph = {"111": {"inputs": {"value": 5}}, "10": {}, "92": {}}
		spec = {
			"parameters": [
				{"semantic": "seed", "node_key": "15", "input_name": "noise_seed"},
				{"semantic": "frame_count", "node_key": "111", "input_name": "value"},
			]
		}
		before = copy.deepcopy((graph, spec))
		converted, execution = image_recipe(graph, spec, "flux-environment")
		self.assertEqual(before, (graph, spec))
		self.assertEqual(73, round(converted["111"]["inputs"]["value"] * 24))
		self.assertEqual(68, converted["storyboard_frame"]["inputs"]["batch_index"])
		self.assertEqual(1, converted["storyboard_frame"]["inputs"]["length"])
		self.assertEqual("Image", execution["outputs"]["primary"]["media_type"])
		self.assertEqual("92", execution["outputs"]["preparation_bridge"]["node_key"])
		self.assertEqual("flux-environment", execution["environment_workflow"])
		self.assertEqual("source_pixels", execution["reference_defaults"]["Product"])
		self.assertNotIn("frame_count", [p["semantic"] for p in execution["parameters"]])

	def test_hold_prompt_numbers_only_bound_references_and_never_performs_the_later_action(self):
		shot = frappe._dict(
			references=[
				frappe._dict(reference_role="Character", asset_version="mascot"),
				frappe._dict(reference_role="Environment", asset_version="room"),
			]
		)
		workflow = frappe._dict(
			bindings=[
				frappe._dict(required_input_role=role) for role in ("character", "product", "environment")
			]
		)
		prompt = compile_opening_hold(
			shot, workflow, "Tight paws and one unfolded white tissue before folding."
		)
		self.assertIn("<Picture 1>", prompt)
		self.assertIn("<Picture 2>", prompt)
		self.assertNotIn("<Picture 3>", prompt)
		self.assertIn("Do not perform the later scripted action", prompt)
		self.assertIn("overall_soundscape: N/A", prompt)
		self.assertIn("non_diegetic_music: N/A", prompt)

	def test_product_free_hold_does_not_inherit_generic_product_boilerplate(self):
		shot = frappe._dict(
			image_prompt="Paws hold one plain unfolded white tissue.",
			motion_plan_json=json.dumps(
				{
					"shot_structure": {
						"stage": "grip",
						"framing": "extreme_close_up",
						"angle": "eye_level",
						"subject_motion": "manipulation",
						"keep_visible": [],
					}
				}
			),
			references=[frappe._dict(reference_role="Character", asset_version="mascot")],
		)
		workflow = frappe._dict(bindings=[frappe._dict(required_input_role="character")])
		prompt = compile_opening_hold(
			shot, workflow, "Show the advertised product and their supports. Add the source-only pink heart."
		)
		self.assertIn(shot.image_prompt, prompt)
		self.assertIn("no retail container", prompt)
		self.assertIn("no full character body", prompt)
		self.assertNotIn("advertised product and their supports", prompt)
		self.assertNotIn("pink heart", prompt)
