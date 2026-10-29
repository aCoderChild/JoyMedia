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
