import io
from unittest import TestCase

import numpy as np
from PIL import Image, ImageDraw

from joymedia.services.intake.view_sheet import split_view_sheet


def png(image):
	output = io.BytesIO()
	image.save(output, "PNG")
	return output.getvalue()


def sheet(heights, width=1600, height=900):
	"""Same-coloured figures side by side on a plain backdrop, each with a caption below."""
	image = Image.new("RGB", (width, height), (252, 250, 245))
	draw = ImageDraw.Draw(image)
	step = width // len(heights)
	for index, figure in enumerate(heights):
		left = index * step + step // 4
		draw.ellipse((left, 120, left + step // 2, 120 + figure), fill=(235, 215, 190))
		draw.rectangle((left + 20, 820, left + step // 2 - 20, 840), fill=(120, 120, 120))
	return png(image)


class TestViewSheet(TestCase):
	def test_a_turnaround_sheet_becomes_one_crop_per_view_without_neighbours_or_captions(self):
		crops = split_view_sheet(sheet([560, 560, 560]))
		self.assertEqual(3, len(crops))
		for crop in crops:
			picture = np.asarray(Image.open(io.BytesIO(crop)).convert("RGB")).astype(int)
			# One figure each: its left and right edges are backdrop, and the caption is left out.
			self.assertTrue((np.abs(picture[:, 0] - [252, 250, 245]).sum(axis=1) < 30).all())
			self.assertTrue((np.abs(picture[:, -1] - [252, 250, 245]).sum(axis=1) < 30).all())
			self.assertLess(Image.open(io.BytesIO(crop)).height, 760)

	def test_photos_and_groups_of_different_subjects_are_not_split(self):
		noise = Image.fromarray(np.random.default_rng(1).integers(0, 255, (900, 1600, 3), dtype=np.uint8))
		self.assertEqual([], split_view_sheet(png(noise)))
		self.assertEqual([], split_view_sheet(sheet([600, 250, 600])))  # an adult and a small object
		self.assertEqual([], split_view_sheet(sheet([560], width=700)))  # one portrait picture
