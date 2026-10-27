from unittest import TestCase

from joymedia.services.project.formats import (
	composition_instruction,
	delivery_dimensions,
	duration_from_description,
	orientation,
	parse_ratio,
	preparation_dimensions,
	ratio_label,
	require_dimensions,
)


class TestAuthoredGeometry(TestCase):
	def test_active_picture_instruction_uses_input_ratio_without_reel_default(self):
		self.assertEqual("", composition_instruction({}))
		for width, height, expected in [(1440, 2560, "9:16"), (1920, 1080, "16:9"), (720, 900, "4:5")]:
			with self.subTest(expected=expected):
				text = composition_instruction({"delivery_width": width, "delivery_height": height})
				self.assertIn(f"full {expected} delivery canvas", text)
				self.assertIn("edge to edge throughout", text)

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

	def test_reference_preparation_uses_declared_preset_before_final_pixels(self):
		self.assertEqual((1024, 576), preparation_dimensions({"delivery_preset": "Landscape"}))
		self.assertEqual((900, 720), preparation_dimensions({}, "5:4", short_edge=720))
		with self.assertRaisesRegex(ValueError, "aspect ratio"):
			preparation_dimensions({})

	def test_duration_uses_units_instead_of_format_numbers(self):
		self.assertEqual(30, duration_from_description("A 4:5 commercial lasting 30 seconds."))
		self.assertEqual(10, duration_from_description("10-second film in 21:9."))
		self.assertIsNone(duration_from_description("A 4:5 commercial."))

	def test_zero_ratios_are_rejected(self):
		for text in ["0:16", "4:0"]:
			with self.assertRaises(ValueError):
				parse_ratio(text)
