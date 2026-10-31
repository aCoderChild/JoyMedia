from unittest import TestCase

import cv2
import numpy as np

from joymedia.services.review.eye_shape import measured_eye_shape


def character(eye):
	"""A pale round character on white with a nose and two eyes of the given kind."""
	image = np.full((400, 300, 3), 255, np.uint8)
	cv2.ellipse(image, (150, 220), (120, 170), 0, 0, 360, (200, 220, 235), -1)
	cv2.ellipse(image, (150, 160), (22, 16), 0, 0, 360, (30, 40, 60), -1)  # nose
	for x in (110, 190):
		if eye == "dot":
			cv2.circle(image, (x, 120), 9, (10, 10, 10), -1)
		else:
			cv2.ellipse(image, (x, 125), (16, 8), 0, 180, 360, (10, 10, 10), 3)
	return cv2.imencode(".png", image)[1].tobytes()


class TestMeasuredEyeShape(TestCase):
	def test_open_dots_and_closed_arcs_are_told_apart(self):
		self.assertEqual("open_dots", measured_eye_shape(character("dot")))
		self.assertEqual("closed_arcs", measured_eye_shape(character("arc")))

	def test_an_unreadable_picture_is_unmeasured(self):
		self.assertIsNone(measured_eye_shape(b"not an image"))
		blank = cv2.imencode(".png", np.full((50, 50, 3), 255, np.uint8))[1].tobytes()
		self.assertIsNone(measured_eye_shape(blank))
