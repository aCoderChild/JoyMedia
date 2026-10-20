from unittest import TestCase

from joymedia.services.project.formats import (
	delivery_dimensions,
	orientation,
	parse_ratio,
	ratio_label,
	require_dimensions,
)


class TestAuthoredGeometry(TestCase):
	def test_arbitrary_ratios_keep_the_authored_shape(self):
		for text, expected in [
			("4:5 product commercial", (720, 900)),
			("21:9 cinema", (1680, 720)),
			("1:1", (720, 720)),
			("1920×1080", (1280, 720)),
			("9:16", (720, 1280)),
		]:
			with self.subTest(text=text):
				ratio = parse_ratio(text)
				self.assertEqual(expected, delivery_dimensions(ratio, 720))
				self.assertEqual(ratio, parse_ratio(ratio_label(*expected)))

	def test_orientation_is_not_a_substitute_for_ratio(self):
		self.assertEqual("Portrait", orientation(parse_ratio("4:5")))
		self.assertEqual("Landscape", orientation(parse_ratio("21:9")))
		self.assertIsNone(parse_ratio("Reels campaign, no specified format"))
		self.assertIsNone(parse_ratio(""))

	def test_missing_dimensions_block_reference_staging(self):
		for snapshot in [{}, {"delivery_width": 720}, {"delivery_width": 0, "delivery_height": 1280}]:
			with self.assertRaisesRegex(ValueError, "aspect ratio"):
				require_dimensions(snapshot)

	def test_zero_ratios_are_rejected(self):
		for text in ["0:16", "4:0"]:
			with self.assertRaises(ValueError):
				parse_ratio(text)
