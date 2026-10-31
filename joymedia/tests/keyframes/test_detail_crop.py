import io
from unittest import TestCase
from unittest.mock import patch

import frappe
from PIL import Image

from joymedia.services.keyframes import detail_crop
from joymedia.services.keyframes.detail_crop import crop_to_detail, crop_window


def png(size):
	out = io.BytesIO()
	Image.new("RGB", size, "white").save(out, format="PNG")
	return out.getvalue()


class TestDetailCrop(TestCase):
	def test_the_window_keeps_the_delivery_aspect_and_never_upscales(self):
		# A small paw region is cropped at exactly the delivery size (a 2x close-up).
		window = crop_window((1440, 2560), (600, 1600, 800, 1800), (720, 1280))
		self.assertEqual((720, 1280), (window[2] - window[0], window[3] - window[1]))
		self.assertTrue(window[0] <= 600 and window[2] >= 800 and window[1] <= 1600 and window[3] >= 1800)
		# A large face region gets a larger window of the same aspect, inside the picture.
		window = crop_window((1440, 2560), (200, 300, 1240, 1300), (720, 1280))
		width, height = window[2] - window[0], window[3] - window[1]
		self.assertAlmostEqual(720 / 1280, width / height, places=2)
		self.assertTrue(height >= 1280 and window[0] >= 0 and window[3] <= 2560)
		# A region at the edge is shifted inside, not cut.
		window = crop_window((1440, 2560), (1400, 2500, 1440, 2560), (720, 1280))
		self.assertEqual((720, 1280, 1440, 2560), window)

	def _attempt(self, scale):
		job = frappe._dict(shot="S", workflow="WF", generation_run="RUN")
		docs = {
			"Generation Task": job,
			"Generation Workflow": frappe._dict(output_media_type="Image"),
			"Shot": frappe._dict(start_state="The mascot's paw near the tissue.", image_prompt=""),
		}
		return (
			patch("frappe.get_doc", side_effect=lambda doctype, name=None: docs[doctype]),
			patch.object(detail_crop, "detail_scale", return_value=scale),
			patch("frappe.db.get_value", return_value='{"delivery_width": 720, "delivery_height": 1280}'),
		)

	def test_other_pictures_pass_through_unchanged(self):
		get_doc, scale, value = self._attempt(1)
		with get_doc, scale, value:
			data = png((720, 1280))
			self.assertIs(data, crop_to_detail(frappe._dict(name="A", generation_task="T"), data))

	def test_a_double_size_close_up_is_cropped_to_its_focus_at_delivery_size(self):
		get_doc, scale, value = self._attempt(2)
		with get_doc, scale, value:
			# The observer sees a 576x1024 thumbnail and answers in its pixels.
			out = crop_to_detail(
				frappe._dict(name="A", generation_task="T"),
				png((1440, 2560)),
				ask=lambda picture, question, **k: {"bbox_2d": [240, 640, 320, 720]},
			)
			self.assertEqual((720, 1280), Image.open(io.BytesIO(out)).size)
			unplaced = crop_to_detail(
				frappe._dict(name="A", generation_task="T"),
				png((1440, 2560)),
				ask=lambda picture, question, **k: {"bbox_2d": None},
			)
			self.assertEqual((720, 1280), Image.open(io.BytesIO(unplaced)).size)
