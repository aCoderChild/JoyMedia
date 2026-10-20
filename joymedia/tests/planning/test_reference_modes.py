from unittest import TestCase
from unittest.mock import patch

from joymedia.services.consistency.retention import needs_identity_review, require_coverage, required_sources
from joymedia.services.keyframes.overlay import closing_subjects, pasted_references
from joymedia.services.planning.workbook import _reference_rows as _references
from joymedia.services.project.context import _compose_end_card


class TestReferenceModes(TestCase):
	def test_hashed_upload_matches_only_a_unique_explicit_sheet_name(self):
		import frappe

		from joymedia.services.intake.references import _match

		ref = frappe._dict(name="one", label="Blue cup (approved view)", asset_version="v1")
		project = frappe._dict(selected_media=[ref])
		row = {"name": "Blue cup", "file": "cup.png"}
		self.assertEqual(ref, _match(row, project, {"one": ("cupab1234", "blue cup approved view")}))
		project.selected_media.append(frappe._dict(name="two", label="Blue cup", asset_version="v2"))
		self.assertIsNone(_match(row, project, {}))

	def test_workbook_preservation_is_explicit_and_checked(self):
		rows = [
			["Name", "Type", "File", "Preservation mode"],
			["Cup", "Product", "cup.png", "reference_guided"],
		]
		self.assertEqual("reference_guided", _references(rows)[0]["preservation_mode"])
		rows[1][3] = ""
		self.assertNotIn("preservation_mode", _references(rows)[0])
		rows[1][3] = "ignore_checks"
		with self.assertRaises(ValueError):
			_references(rows)

	def test_opening_control_survives_the_workbook_parser(self):
		from tempfile import NamedTemporaryFile

		from openpyxl import Workbook

		from joymedia.services.planning.workbook import read_workbook

		book = Workbook()
		sheet = book.active
		sheet.append(["Product", "Cup"])
		sheet.append(["Duration", "3s"])
		sheet.append(["Scene", "Timing", "Action", "Opening reference"])
		sheet.append(["Lift", "0:00 - 0:03", "Lift the cup.", "approved_cup_opening"])
		with NamedTemporaryFile(suffix=".xlsx") as f:
			book.save(f.name)
			scene = read_workbook(f.name)["demos"][0]["scenes"][0]
		self.assertEqual("approved_cup_opening", scene["opening_reference"])

	def test_guided_product_keeps_its_role_and_mandatory_review(self):
		exact = {"reference_role": "Product", "asset_version": "exact"}
		guided = {
			"reference_role": "Product",
			"asset_version": "guided",
			"preservation_mode": "reference_guided",
		}
		self.assertEqual(["exact"], required_sources([exact, guided]))
		self.assertTrue(needs_identity_review({"references": [guided]}))
		require_coverage({"reference_retention": True, "references": [guided]}, {})
		with self.assertRaises(ValueError):
			require_coverage({"reference_retention": True, "references": [exact, guided]}, {})
		with patch(
			"joymedia.services.keyframes.overlay._cutout_path",
			side_effect=AssertionError("must not paste appearance reference"),
		):
			self.assertEqual([], pasted_references([guided]))
		with patch(
			"joymedia.services.keyframes.overlay._any_image_path",
			side_effect=AssertionError("must not paste appearance reference"),
		):
			self.assertEqual([], closing_subjects([guided]))

	def test_locomotion_ending_does_not_freeze_the_authored_last_two_seconds(self):
		shot = {
			"duration_seconds": 5,
			"references": [{"reference_role": "Product"}],
			"motion_plan_json": {
				"shot_structure": {
					"stage": "approach",
					"framing": "medium",
					"angle": "eye_level",
					"subject_motion": "locomotion",
					"keep_visible": [],
				}
			},
		}
		_compose_end_card([shot])
		self.assertNotIn("closing_hold_seconds", shot)
