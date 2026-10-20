from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.intake import references as sheet


def _project(rows, pictures):
	project = frappe._dict(name="PRJ-X", storyboard_source_json=frappe.as_json({"references": rows}), selected_media=pictures)
	project.save = lambda **kwargs: None
	return project


def _picture(name, label, role="General", version=None):
	row = frappe._dict(name=name, label=label, reference_role=role, relative_size=None, keep_rule="", asset_version=version or f"AV-{name}")
	row.update = row.__class__.update.__get__(row)
	return row


class TestSheetReferences(FrappeTestCase):
	def test_names_are_compared_without_accents_case_or_extension(self):
		self.assertEqual("be mai", sheet.plain("Bé_Mai.PNG"))
		self.assertEqual(sheet.plain("Giấy rút Shera 400 tờ"), sheet.plain("giay rut shera 400 to"))

	def test_only_the_pdf_pages_the_sheet_names_are_taken(self):
		rows = [{"file": "catalogue.pdf", "pdf_page": 8}, {"file": "Catalogue.PDF", "pdf_page": 2}, {"file": "other.pdf", "pdf_page": 5}]
		self.assertEqual([2, 8], sheet.pdf_pages(rows, "catalogue.pdf"))
		self.assertEqual([], sheet.pdf_pages(rows, "brochure.pdf"))

	def test_a_row_gives_its_picture_name_role_size_and_rule_and_a_missing_file_is_reported(self):
		rows = [
			{"name": "Gấu con", "role": "Character", "file": "gau_con.png", "pdf_page": None, "description": "kid mascot",
			 "family_role": "con", "relative_size": None, "keep_rule": "Không thêm quần áo"},
			{"name": "Shera 400", "role": "Product", "file": "catalogue.pdf", "pdf_page": 8, "description": "", "family_role": "",
			 "relative_size": None, "keep_rule": "Tờ giấy rút, không phải cuộn"},
			{"name": "Logo", "role": "Logo", "file": "logo.png", "pdf_page": None, "description": "", "family_role": "",
			 "relative_size": None, "keep_rule": ""},
			{"name": "Phòng khách", "role": "Environment", "file": "", "pdf_page": None, "description": "Phòng nhỏ", "family_role": "",
			 "relative_size": None, "keep_rule": ""},
		]
		kid = _picture("R1", "gau_con")
		small, pack = _picture("R2", "catalogue p8 X16"), _picture("R3", "catalogue p8 X19")
		project = _project(rows, [kid, small, pack])
		names = {"R1": ("gau con", "gau con"), "R2": ("x16", "catalogue p8 x16"), "R3": ("x19", "catalogue p8 x19")}
		with patch.object(frappe, "get_doc", return_value=project), patch.object(sheet, "_picture_names", return_value=names), \
			patch.object(sheet, "_picture_area", side_effect=lambda version: {"AV-R2": 100, "AV-R3": 900}[version]):
			result = sheet.apply_sheet_references("PRJ-X")
		self.assertEqual(["Gấu con", "Shera 400"], result["matched"])
		self.assertEqual(["Logo"], result["missing"])  # the AI-drawn place needs no file
		self.assertEqual(("Gấu con (kid mascot)", "Character", 0.55, "Không thêm quần áo"), (kid.label, kid.reference_role, kid.relative_size, kid.keep_rule))
		self.assertEqual(("Shera 400", "Product"), (pack.label, pack.reference_role))  # the largest picture of page 8
		self.assertEqual("catalogue p8 X16", small.label)

	def test_a_script_name_finds_its_reference(self):
		options = [{"key": "gau_me", "label": "Gấu mẹ (mother mascot)", "role": "Character"}, {"key": "gau_con", "label": "Gấu con", "role": "Character"}]
		self.assertEqual("gau_con", sheet.find_reference("gấu con", options)["key"])
		self.assertEqual("gau_me", sheet.find_reference("Gau me", options)["key"])
		self.assertIsNone(sheet.find_reference("Gấu bố", options))
