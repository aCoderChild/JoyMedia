import copy
from unittest import TestCase

from joymedia.services.planning.reference_plan import (
	build_reference_plan,
	environment_entities,
	environment_staging,
	ground_generated_inventory,
	script_fingerprint,
)


class TestReferencePlan(TestCase):
	def test_inventory_repairs_authored_support_quotes_but_excludes_named_subjects(self):
		script = {
			"scenes": [
				{
					"place": "Room with a broad rug",
					"visual_camera": "The mascot sits beside the Shera Facial pack.",
					"environment_entities": [
						{"name": "rug", "kind": "support", "source_quote": "large carpet"},
						{
							"name": "Shera Facial pack",
							"kind": "working_prop",
							"source_quote": "Shera Facial pack",
						},
						{"name": "mascot", "kind": "background", "source_quote": "mascot"},
					],
				}
			]
		}
		ground_generated_inventory(script)
		self.assertEqual(
			[{"name": "rug", "kind": "support", "source_quote": "rug"}],
			script["scenes"][0]["environment_entities"],
		)
		self.assertEqual(2, len(script["inventory_rejections"]))
		self.assertEqual(1, len(script["inventory_repairs"]))

	def test_generated_inventory_drops_invented_annotations_without_changing_the_story(self):
		scene = {
			"place": "Living room with a rug",
			"action": "The mascot folds the loose paper.",
			"environment_entities": [
				{"name": "rug", "kind": "support", "source_quote": "rug"},
				{"name": "child", "kind": "background", "source_quote": "Living room"},
				{"name": "couch", "kind": "furnishing", "source_quote": "Living room"},
			],
		}
		script = {"scenes": [scene]}
		changes = ground_generated_inventory(script)
		self.assertEqual(2, len(changes))
		self.assertEqual(2, len(script["inventory_rejections"]))
		self.assertEqual(["rug"], [row["name"] for row in scene["environment_entities"]])
		self.assertEqual("The mascot folds the loose paper.", scene["action"])
		self.assertEqual("Living room with a rug", scene["place"])
		self.assertEqual([], ground_generated_inventory(script))
		self.assertEqual(2, len(script["inventory_rejections"]))

	def test_location_inventory_excludes_transient_materials_and_other_scenes(self):
		plan = {
			"environments": [
				{
					"objects": [
						{"scene": 1, "kind": "support", "name": "rug"},
						{"scene": 1, "kind": "furnishing", "name": "sofa"},
						{"scene": 1, "kind": "material", "name": "paper"},
						{"scene": 1, "kind": "working_prop", "name": "cup"},
						{"scene": 2, "kind": "support", "name": "table"},
					]
				}
			]
		}
		self.assertEqual("rug, sofa", environment_staging(plan, 1))
		self.assertEqual("", environment_staging(None, 1))

	def test_plan_groups_identities_and_preserves_scene_action_view_and_empty_environment(self):
		registry = [
			{
				"identity": "actor",
				"role": "character",
				"label": "Mascot",
				"original": {"asset_version": "original", "content_hash": "hash"},
				"views": [{"reference_key": "front"}, {"reference_key": "seated"}],
			},
			{
				"identity": "pack",
				"role": "product",
				"label": "Product",
				"original": {"asset_version": "photo"},
				"views": [{"reference_key": "pack_front"}],
			},
		]
		script = {
			"scenes": [
				{
					"cast": ["front"],
					"products": ["pack_front"],
					"place": "Living room with a low table",
					"visual_camera": "Mascot seated beside the low table.",
					"action": "[0-2s] The mascot reaches toward the pack.",
					"opening_support": "seated",
					"product_view": "front_left",
					"environment_entities": [
						{"name": "low table", "kind": "support", "source_quote": "low table"}
					],
				},
				{
					"cast": ["seated"],
					"products": [],
					"place": "Living room with a low table",
					"action": "[0-2s] The mascot holds a tissue.",
				},
				{
					"cast": [],
					"products": ["pack_front"],
					"place": "Living room with a low table",
					"product_view": "source",
				},
			]
		}
		before = copy.deepcopy(script)
		plan = build_reference_plan(script, registry)
		self.assertEqual(before, script)
		self.assertEqual(1, len(plan["characters"]))
		self.assertEqual(2, len(plan["characters"][0]["requirements"]))
		self.assertEqual("front_left", plan["products"][0]["requirements"][0]["view"])
		self.assertEqual(
			"[0-2s] The mascot holds a tissue.", plan["characters"][0]["requirements"][1]["action"]
		)
		self.assertEqual([], plan["environments"][0]["physical_cast"])
		self.assertEqual([], plan["scenes"][2]["cast_ids"])
		self.assertEqual("original", plan["characters"][0]["original"]["asset_version"])
		self.assertEqual(script_fingerprint(script), plan["script_sha256"])

	def test_environment_inventory_cannot_invent_an_object_or_source_quote(self):
		for entity in (
			{"name": "child", "kind": "background", "source_quote": "living room"},
			{"name": "chair", "kind": "support", "source_quote": "a chair"},
			{"name": "room", "kind": "actor", "source_quote": "living room"},
		):
			with self.subTest(entity=entity), self.assertRaises(ValueError):
				environment_entities({"place": "A living room", "environment_entities": [entity]})

	def test_unknown_cast_fails_before_reference_preparation(self):
		with self.assertRaisesRegex(ValueError, "unregistered cast"):
			build_reference_plan({"scenes": [{"cast": ["unregistered child"]}]}, [])

	def test_invalid_quote_reports_the_object_and_scene_text_needed_for_repair(self):
		with self.assertRaisesRegex(ValueError, "couch.*living room.*Available scene text:.*rug"):
			environment_entities(
				{
					"place": "Living room with a rug",
					"environment_entities": [
						{"name": "couch", "kind": "furnishing", "source_quote": "living room"}
					],
				}
			)
