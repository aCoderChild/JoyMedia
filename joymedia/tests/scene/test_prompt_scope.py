from unittest import TestCase
from unittest.mock import patch

from joymedia.services.scene.prompt_scope import (
	assert_product_only_direction,
	product_only_instruction,
	reference_description,
	sheet_material_instruction,
)


class TestPromptScope(TestCase):
	def test_package_lock_does_not_confuse_held_contents_with_a_held_package(self):
		from joymedia.services.planning.creative import unheld_package_opening_errors

		for opening in (
			"The mascot holds the pack.",
			"The mascot is holding a blue tissue package.",
			"The box is held by the mascot.",
		):
			with self.subTest(opening=opening):
				self.assertTrue(unheld_package_opening_errors({"scenes": [{"visual_camera": opening}]}))
		for opening in (
			"The mascot holds a tissue from the pack.",
			"The mascot holds tissue from pack.",
			"The pack is not held; it rests on the rug.",
			"The mascot holds a sheet beside the box.",
		):
			with self.subTest(opening=opening):
				self.assertEqual([], unheld_package_opening_errors({"scenes": [{"visual_camera": opening}]}))

	def test_handled_sheet_keeps_paper_material_but_a_pack_is_not_a_sheet(self):
		self.assertIn(
			"thin, lightweight, flexible",
			sheet_material_instruction("Extract a single tissue from the pack and unfold it."),
		)
		self.assertEqual("", sheet_material_instruction("Extract the tissue pack from the bag."))
		for action in ("Hold the tissue up to the light.", "Place the tissue flat on the table."):
			with self.subTest(action=action):
				self.assertIn("thin, lightweight, flexible", sheet_material_instruction(action))
		self.assertEqual(
			"", sheet_material_instruction("The original product remains in its established position.")
		)

	def test_literal_static_product_hold_uses_source_presentation_only_with_locked_camera(self):
		from joymedia.services.consistency.retention import (
			authored_static_product_hold,
			is_static_presentation,
		)

		scene = {
			"references": [{"reference_role": "product", "asset_version": "P"}],
			"motion_plan_json": {
				"actions": [
					{
						"action": "The original product remains in its established position with its printed artwork intact."
					}
				]
			},
		}
		self.assertTrue(authored_static_product_hold(scene))
		self.assertFalse(is_static_presentation(scene))
		scene["effective_camera_behavior"] = "locked"
		self.assertTrue(is_static_presentation(scene))
		scene["motion_plan_json"]["actions"][0]["action"] = (
			"Extract and unfold a single tissue from the pack."
		)
		self.assertFalse(authored_static_product_hold(scene))
		self.assertFalse(is_static_presentation(scene))

	def test_product_only_direction_rejects_stale_actor_continuity(self):
		for text in (
			"The mascot is seated beside the table.",
			"A fox remains sitting on the rug.",
			"The character waves.",
		):
			with self.subTest(text=text), self.assertRaisesRegex(ValueError, "declares no actor"):
				assert_product_only_direction(text)

	def test_flat_package_artwork_and_supported_product_are_not_cast(self):
		assert_product_only_direction("A printed character is seated in the package artwork.")
		assert_product_only_direction("The pack remains on the table with its original artwork.")
		assert_product_only_direction("The sheet reaches the tabletop and settles.")
		instruction = product_only_instruction([{"reference_role": "Product"}])
		self.assertIn("no physical actors or toys", instruction)
		self.assertIn("flat printed artwork", instruction)
		self.assertEqual(
			"", product_only_instruction([{"reference_role": "Product"}, {"reference_role": "Character"}])
		)

	def test_pose_caption_does_not_replace_fixed_appearance(self):
		self.assertEqual(
			"Cream smooth mascot with two round ears.",
			reference_description(
				{
					"description": "Same character in a seated pose",
					"identity_appearance": {"appearance": "Cream smooth mascot with two round ears."},
				},
				"character",
			),
		)

	def test_frozen_identity_text_does_not_read_changed_database_captions(self):
		from joymedia.services.planning.h3 import subject_identities

		with patch("frappe.db.get_value", side_effect=AssertionError("Frozen captions must not change")):
			text = subject_identities(
				{
					"references": [
						{
							"reference_role": "character",
							"asset_version": "pose",
							"visual_description": "Cream mascot with two round ears and closed smiling eyes.",
						}
					]
				}
			)
		self.assertIn("two round ears", text)
		self.assertIn("closed smiling eyes", text)

	def test_ai_packshot_normalizer_repairs_empty_cast_with_stale_actor_rules(self):
		from joymedia.services.planning.creative import normalize_static_final_packshot

		scene = {
			"cast": [],
			"products": ["product"],
			"action": "The original product remains still.",
			"continuity_rules": "The bear is seated on the rug.",
			"on_screen_text": "Shop Now",
		}
		self.assertTrue(normalize_static_final_packshot({"scenes": [scene]}))
		self.assertEqual("The original product remains still.", scene["action"])
		self.assertEqual("Shop Now", scene["on_screen_text"])
		self.assertNotIn("bear", scene["continuity_rules"])
