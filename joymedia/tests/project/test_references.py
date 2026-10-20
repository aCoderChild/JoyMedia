import unittest

from joymedia.services.project.references import (
	canonical_reference_rows,
	expand_reference_keys,
	identity_key,
)


class TestCanonicalProjectReferences(unittest.TestCase):
	def setUp(self):
		self.rows = [
			{"reference_key": "mascot_front", "identity_key": "mascot", "asset_version": "AV-FRONT"},
			{"reference_key": "mascot_side", "identity_key": "mascot", "asset_version": "AV-SIDE"},
			{"reference_key": "product_pack", "identity_key": "product_pack", "asset_version": "AV-PACK"},
		]

	def test_variants_are_one_planning_identity(self):
		self.assertEqual(
			["mascot_front", "product_pack"],
			[row["reference_key"] for row in canonical_reference_rows(self.rows)],
		)

	def test_selecting_one_view_expands_to_its_approved_variants(self):
		expanded = expand_reference_keys(self.rows, ["mascot_side", "product_pack"])
		self.assertEqual(["AV-FRONT", "AV-SIDE", "AV-PACK"], [row["asset_version"] for row in expanded])

	def test_legacy_reference_without_identity_is_its_own_identity(self):
		self.assertEqual("legacy", identity_key({"reference_key": "legacy"}))

	def test_explicit_view_keeps_one_identity_without_importing_other_poses(self):
		expanded = expand_reference_keys(
			self.rows, ["mascot_front", "product_pack"], view_keys=["mascot_side"]
		)
		self.assertEqual(["AV-SIDE", "AV-PACK"], [row["asset_version"] for row in expanded])
		self.assertEqual("mascot", identity_key(expanded[0]))

	def test_view_cannot_introduce_an_undeclared_identity(self):
		with self.assertRaises(ValueError):
			expand_reference_keys(self.rows, ["product_pack"], view_keys=["mascot_side"])
		with self.assertRaises(ValueError):
			expand_reference_keys(self.rows, ["mascot_front"], view_keys=["unknown"])

	def test_workbook_view_names_are_exact_and_do_not_guess_from_actions(self):
		from joymedia.services.scene.references import named_reference_views

		self.rows[0]["label"] = "Approved subject front"
		self.rows[1]["label"] = "Approved subject side (the approved side photograph)"
		self.assertEqual(["mascot_side"], named_reference_views(self.rows, ["Approved subject side"]))
		self.assertEqual([], named_reference_views(self.rows, ["subject turns sideways"]))
