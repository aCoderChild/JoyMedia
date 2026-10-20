from unittest import TestCase

from joymedia.services.consistency.plan import identity_plan


class TestIdentityPlan(TestCase):
	def test_multiple_views_are_one_identity_and_print_is_not_generated(self):
		references = [
			{"identity_key": "performer", "reference_role": "Character", "asset_version": v}
			for v in ["FRONT", "SIDE"]
		]
		references += [{"reference_role": "Product", "asset_version": "PACK"}]
		plan = identity_plan(references, ["reference_image"])
		self.assertEqual(len(plan["identities"]), 2)
		self.assertEqual(plan["identities"][0]["strategy"], "reference_conditioned")
		self.assertEqual(plan["identities"][1]["strategy"], "source_artwork")
		self.assertEqual(
			plan["fingerprint"], identity_plan(list(reversed(references)), ["reference_image"])["fingerprint"]
		)

	def test_a_different_source_or_model_control_changes_the_frozen_plan(self):
		reference = {"reference_role": "Logo", "asset_version": "ART"}
		base = identity_plan([reference])
		self.assertNotEqual(
			base["fingerprint"], identity_plan([{**reference, "asset_version": "NEW"}])["fingerprint"]
		)
		self.assertNotEqual(
			base["fingerprint"], identity_plan([reference], ["reference_video"])["fingerprint"]
		)

	def test_original_semantic_role_survives_provider_binding_names(self):
		plan = identity_plan(
			[{"input_role": "Character", "reference_role": "reference_board", "asset_version": "PERFORMER"}],
			["rigged_render"],
		)
		self.assertEqual(plan["identities"][0]["strategy"], "rigged_render")
