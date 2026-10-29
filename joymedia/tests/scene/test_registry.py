from unittest import TestCase

from joymedia.services.scene.registry import reference_registry, scene_reference_bindings


class TestReferenceRegistry(TestCase):
	def records(self):
		return [
			{
				"identity_key": "mascot",
				"reference_key": "mascot_front",
				"reference_role": "Character",
				"asset_version": "original",
				"original": {"asset_version": "original", "content_hash": "source-hash"},
				"angle": "front",
				"status": "supplied",
			},
			{
				"identity_key": "mascot",
				"reference_key": "seated_side",
				"reference_role": "Character",
				"asset_version": "pose",
				"original": {"asset_version": "original", "content_hash": "source-hash"},
				"pose": "seated",
				"angle": "side",
				"status": "qualified_pose",
			},
			{
				"identity_key": "product",
				"reference_key": "pack",
				"reference_role": "Product",
				"asset_version": "pack",
				"angle": "source",
				"status": "supplied",
			},
			{
				"identity_key": "product",
				"reference_key": "pack_back",
				"reference_role": "Product",
				"asset_version": "back",
				"angle": "back",
				"status": "ai_extrapolated_candidate",
			},
		]

	def test_poses_and_product_angles_remain_views_of_the_same_identity(self):
		registry = reference_registry(self.records())
		self.assertEqual(2, len(registry))
		self.assertEqual(["front", "side"], [v["angle"] for v in registry[0]["views"]])
		self.assertEqual("ai_extrapolated_candidate", registry[1]["views"][1]["status"])
		bindings = scene_reference_bindings(
			[
				{"reference_role": "character", "asset_version": "pose"},
				{"reference_role": "product", "asset_version": "pack"},
			],
			registry,
		)
		self.assertEqual("original", bindings[0]["original"]["asset_version"])
		self.assertEqual("side", bindings[0]["view"]["angle"])
		self.assertEqual("seated", bindings[0]["view"]["pose"])
		self.assertEqual("mascot", bindings[0]["identity"])

	def test_empty_environment_cast_and_product_artwork_do_not_create_actors(self):
		registry = reference_registry(self.records())
		self.assertEqual(
			[],
			scene_reference_bindings([{"reference_role": "environment", "asset_version": "room"}], registry),
		)
		bindings = scene_reference_bindings(
			[{"reference_role": "product", "asset_version": "pack"}], registry
		)
		self.assertTrue(all(b["role"] == "product" for b in bindings))

	def test_unregistered_actor_or_wrong_role_fails_before_execution(self):
		registry = reference_registry(self.records())
		for version in ("invented-child", "pack"):
			with self.subTest(version=version), self.assertRaisesRegex(ValueError, "unregistered"):
				scene_reference_bindings(
					[{"reference_role": "character", "asset_version": version}], registry
				)

	def test_one_view_cannot_be_registered_as_two_characters(self):
		records = self.records()
		records.append({**records[0], "identity_key": "another-mascot"})
		with self.assertRaisesRegex(ValueError, "two different identities"):
			reference_registry(records)
