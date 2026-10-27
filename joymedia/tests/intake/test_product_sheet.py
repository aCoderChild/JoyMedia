from io import BytesIO
from unittest import TestCase

from PIL import Image

from joymedia.services.intake.product_sheet import transparent_product_cutout, white_background_crop


class TestWhiteBackgroundProductCrop(TestCase):
	def test_preserves_source_pixels_and_uses_pure_white_canvas(self):
		source = Image.new("RGB", (40, 30), (12, 89, 176))
		output = Image.open(BytesIO(white_background_crop(source, (5, 3, 25, 13), size=128)))
		self.assertEqual((128, 128), output.size)
		self.assertEqual((255, 255, 255), output.getpixel((0, 0)))
		self.assertEqual((12, 89, 176), output.getpixel((54, 59)))
		self.assertEqual((255, 255, 255), output.getpixel((53, 59)))

	def test_rejects_out_of_bounds_crop(self):
		with self.assertRaises(ValueError):
			white_background_crop(Image.new("RGB", (10, 10)), (0, 0, 11, 10))

	def test_reviewed_outline_preserves_opaque_source_pixels(self):
		source = Image.new("RGB", (80, 80), "white")
		for x in range(20, 61):
			for y in range(20, 61):
				source.putpixel((x, y), (x, y, 120))
		cutout = Image.open(
			BytesIO(transparent_product_cutout(source, [(20, 20), (60, 20), (60, 60), (20, 60)]))
		)
		self.assertEqual(0, cutout.getpixel((0, 0))[3])
		self.assertEqual((40, 40, 120, 255), cutout.getpixel((32, 32)))

	def test_cutout_outline_must_be_inside_image(self):
		with self.assertRaises(ValueError):
			transparent_product_cutout(Image.new("RGB", (40, 40)), [(1, 1), (41, 1), (30, 30), (1, 30)])
