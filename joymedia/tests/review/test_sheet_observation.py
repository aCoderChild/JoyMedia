from unittest import TestCase
from unittest.mock import patch

from joymedia.services.review.sheet_observation import observe_sheet, sheet_marking_results


class TestSheetObservation(TestCase):
	def test_printed_cartoon_cannot_be_hidden_by_a_positive_claim(self):
		def observe(picture, **kwargs):
			return {
				"visibility": "visible",
				"printed_marks": ["cartoon and stars"] if picture == b"printed" else [],
				"description": "Observed sheet surface.",
				"quote": "Observed sheet surface.",
				"verdict": "supported",
			}

		r = sheet_marking_results(
			[b"blank", b"printed", b"blank"], {"generation_prompt": "Fold the white tissue."}, observe=observe
		)[0]
		self.assertEqual("violated", r["verdict"])
		self.assertEqual([1], r["frames"])
		self.assertEqual(["cartoon and stars"], r["observations"][1]["printed_marks"])

	def test_absent_or_unclear_sheet_does_not_invent_print(self):
		for answer, expected in [
			({"visibility": "absent", "printed_marks": []}, "supported"),
			({"visibility": "unclear", "printed_marks": None}, "uncertain"),
			({"visibility": "absent", "printed_marks": ["logo"]}, "uncertain"),
		]:
			r = sheet_marking_results(
				[b"frame"], {"generation_prompt": "Hold the tissue."}, observe=lambda *a, **k: answer
			)
			self.assertEqual(expected, r[0]["verdict"])

	def test_text_extraction_must_quote_the_actual_visual_description(self):
		description = "A bear holds paper with an illustration and gold stars."
		with (
			patch("joymedia.services.review.consistency.ask", return_value={"description": description}),
			patch(
				"joymedia.services.review.sheet_observation._parse_description",
				return_value={"visibility": "visible", "printed_marks": [], "quote": "The sheet is blank."},
			),
		):
			self.assertEqual("unclear", observe_sheet(b"frame")["visibility"])

	def test_explicit_print_is_distinct_from_a_forbidden_printed_sheet(self):
		self.assertEqual(
			[], sheet_marking_results([b"frame"], {"generation_prompt": "Hold the printed paper."})
		)
		r = sheet_marking_results(
			[b"frame"],
			{"generation_prompt": "Hold the paper. No printed paper."},
			observe=lambda *a, **k: {"visibility": "visible", "printed_marks": ["logo"]},
		)
		self.assertEqual("violated", r[0]["verdict"])

	def test_package_artwork_described_near_the_sheet_is_not_sheet_print(self):
		description = (
			"A bear holds a plain white tissue. In front of the bear, there is a box of Shera facial "
			"tissue. The brand name 'Shera' is displayed in white text on a dark blue oval."
		)
		parsed = {
			"visibility": "visible",
			"quote": "A bear holds a plain white tissue.",
			"printed_marks": [
				{"mark": "Shera logo", "quote": "there is a box of Shera facial tissue"},
				{"mark": "brand name", "quote": "The brand name 'Shera' is displayed in white text"},
			],
		}
		with (
			patch("joymedia.services.review.consistency.ask", return_value={"description": description}),
			patch("joymedia.services.review.sheet_observation._parse_description", return_value=parsed),
		):
			observed = observe_sheet(b"frame")
		self.assertEqual([], observed["printed_marks"])
		self.assertEqual(["Shera logo", "brand name"], observed["marks_not_on_sheet"])

	def test_print_placed_on_the_sheet_is_kept_even_near_a_package(self):
		description = "A tissue with a cartoon bear and stars is pulled from the box."
		parsed = {
			"visibility": "visible",
			"quote": "A tissue with a cartoon bear",
			"printed_marks": [{"mark": "cartoon bear", "quote": description}],
		}
		with (
			patch("joymedia.services.review.consistency.ask", return_value={"description": description}),
			patch("joymedia.services.review.sheet_observation._parse_description", return_value=parsed),
		):
			self.assertEqual(["cartoon bear"], observe_sheet(b"frame")["printed_marks"])

	def test_a_mark_without_its_own_verbatim_quote_stays_unclear(self):
		description = "A bear holds a tissue with a drawing."
		parsed = {
			"visibility": "visible",
			"quote": "A bear holds a tissue",
			"printed_marks": [{"mark": "drawing", "quote": "The sheet shows a drawing."}],
		}
		with (
			patch("joymedia.services.review.consistency.ask", return_value={"description": description}),
			patch("joymedia.services.review.sheet_observation._parse_description", return_value=parsed),
		):
			self.assertEqual("unclear", observe_sheet(b"frame")["visibility"])

	def test_a_dropped_quote_is_recovered_from_the_sheets_own_sentence(self):
		# Recorded from a rejected frame (ATT-02772): the description plainly says the sheet is blank.
		description = (
			"The image features a plush toy resembling a polar bear sitting on a textured surface. "
			"The surface beneath the bear appears to be a soft, textured rug with subtle white patterns. "
			"A loose sheet of paper lies in front of the bear, partially crumpled, with no visible graphics, "
			"drawings, or lettering. The material of the sheet seems to be plain, possibly white."
		)
		dropped = {"printed_marks": [], "quote": "", "visibility": "absent"}
		with (
			patch("joymedia.services.review.consistency.ask", return_value={"description": description}),
			patch("joymedia.services.review.sheet_observation._parse_description", return_value=dropped),
		):
			observed = observe_sheet(b"frame")
		self.assertEqual(("visible", []), (observed["visibility"], observed["printed_marks"]))
		self.assertNotIn("rug", observed["quote"])
		printed = description.replace(
			"with no visible graphics, drawings, or lettering", "with a cartoon logo"
		)
		with (
			patch("joymedia.services.review.consistency.ask", return_value={"description": printed}),
			patch("joymedia.services.review.sheet_observation._parse_description", return_value=dropped),
		):
			self.assertEqual("unclear", observe_sheet(b"frame")["visibility"])

	def test_the_packages_printed_text_is_not_read_as_the_sheets(self):
		from joymedia.services.review.sheet_observation import _sheet_sentence, _unnegated_mark

		description = (
			"The text on the box indicates it contains 400 tissues. The surface of the loose sheet appears "
			"to be smooth and white, with no colored shapes, drawings, or lettering present."
		)
		sentence = _sheet_sentence(description)
		self.assertTrue(sentence.startswith("The surface of the loose sheet"))
		self.assertFalse(_unnegated_mark(sentence))

	def test_a_description_that_skips_the_sheet_gets_one_focused_look(self):
		answers = [
			{"description": "A plush bear with a yellow flower sits upright on a textured rug."},
			{"description": "The loose tissue sheet is plain white with no drawings, logos or lettering."},
		]
		with (
			patch("joymedia.services.review.consistency.ask", side_effect=answers) as ask,
			patch(
				"joymedia.services.review.sheet_observation._parse_description",
				return_value={"printed_marks": [], "quote": "", "visibility": "absent"},
			),
		):
			observed = observe_sheet(b"frame")
		self.assertEqual(2, ask.call_count)
		self.assertEqual(("visible", []), (observed["visibility"], observed["printed_marks"]))

	def test_an_unclear_first_look_gets_one_look_at_the_sheet_alone(self):
		# Recorded from CRB-00126 scene 3: the patterned rug was read as the sheet.
		rug = (
			"The image shows a plush toy resembling a polar bear sitting on a textured surface that appears to "
			"be a loose sheet or rug. The surface is covered with small, irregular patterns."
		)
		sheet = "The loose tissue sheet is plain white with soft creases and no drawings, logos or lettering."
		answers = [{"description": rug}, {"description": sheet}]
		parsed = {"printed_marks": [], "quote": "", "visibility": "unclear"}
		with (
			patch("joymedia.services.review.consistency.ask", side_effect=answers),
			patch("joymedia.services.review.sheet_observation._parse_description", return_value=parsed),
		):
			observed = observe_sheet(b"frame")
		self.assertEqual(("visible", []), (observed["visibility"], observed["printed_marks"]))
