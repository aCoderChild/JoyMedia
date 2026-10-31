from unittest import TestCase

import cv2
import numpy as np

from joymedia.services.planning.product_views import _colour_retained, restore_printed_face


def pack(text):
	"""A blue pack with a logo-like mark and a line of print on a white backdrop."""
	image = np.full((480, 640, 3), 255, np.uint8)
	cv2.rectangle(image, (80, 120), (560, 360), (220, 160, 60), -1)
	cv2.ellipse(image, (200, 220), (70, 40), 0, 0, 360, (90, 20, 20), -1)
	cv2.circle(image, (450, 250), 45, (180, 200, 240), -1)
	cv2.putText(image, text, (110, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
	for x in range(100, 540, 37):
		cv2.line(image, (x, 140), (x + 20, 170), (255, 230, 200), 2)
	return image


class TestPrintRestoration(TestCase):
	def test_the_photographs_print_is_put_back_on_a_tilted_candidate(self, tmp_path=None):
		import tempfile

		source = pack("400 TO | 4 LOP")
		# The candidate: the same pack seen at a slant, its print redrawn wrongly.
		tilt = cv2.getPerspectiveTransform(
			np.float32([[0, 0], [640, 0], [640, 480], [0, 480]]),
			np.float32([[30, 20], [610, 0], [620, 470], [10, 450]]),
		)
		candidate = cv2.warpPerspective(pack("900 TO | 4 LUP"), tilt, (640, 480), borderValue=(255, 255, 255))
		with tempfile.NamedTemporaryFile(suffix=".png") as handle:
			cv2.imwrite(handle.name, source)
			_ok, encoded = cv2.imencode(".png", candidate)
			restored = restore_printed_face(handle.name, encoded.tobytes())
			self.assertIsNotNone(restored)
			restored_image = cv2.imdecode(np.frombuffer(restored, np.uint8), cv2.IMREAD_COLOR)
			expected = cv2.warpPerspective(source, tilt, (640, 480), borderValue=(255, 255, 255))
			print_band = (slice(300, 345), slice(120, 420))
			error = np.abs(restored_image[print_band].astype(int) - expected[print_band].astype(int)).mean()
			# The restored print is the photograph's, in the candidate's perspective (0-255 scale).
			self.assertLess(error, 3)
			self.assertTrue(_colour_retained(handle.name, restored))

	def test_an_unrelated_picture_is_not_restored(self):
		import tempfile

		with tempfile.NamedTemporaryFile(suffix=".png") as handle:
			cv2.imwrite(handle.name, pack("400 TO | 4 LOP"))
			blank = np.full((480, 640, 3), 128, np.uint8)
			_ok, encoded = cv2.imencode(".png", blank)
			self.assertIsNone(restore_printed_face(handle.name, encoded.tobytes()))


class TestObservedHeroView(TestCase):
	def test_the_view_a_candidate_really_shows_is_recorded_for_front_visible_requests(self):
		from unittest.mock import patch

		from joymedia.services.planning import product_views as pv

		shows = {"three_quarter"}
		with patch.object(pv, "_candidate_matches_requested_view", side_effect=lambda c, v: v in shows):
			self.assertEqual("three_quarter", pv._observed_hero_view(b"c", "front_left"))
			shows.clear()
			self.assertEqual("front", pv._observed_hero_view(b"c", "front_left"))
			# A back view is never replaced by a front one.
			self.assertIsNone(pv._observed_hero_view(b"c", "back"))

	def test_a_candidate_made_for_the_requested_view_is_chosen_for_it(self):
		from unittest.mock import patch

		import frappe

		from joymedia.services.planning import product_views as pv

		photo = frappe._dict(reference_key="product", product_view="source")
		angle = frappe._dict(reference_key="product_view_x", product_view="three_quarter")
		analyses = {"product": {}, "product_view_x": {"requested_view": "front_left"}}
		with (
			patch.object(pv, "_analysis", side_effect=lambda row: analyses[row.reference_key]),
			patch.object(pv, "_view_candidate_qualified", return_value=True),
			patch.object(pv, "is_extrapolated_product_view", side_effect=lambda row: row is angle),
			patch.object(pv, "product_view_kind", side_effect=lambda row: row.product_view),
		):
			chosen, supported = pv._choose_view([photo, angle], "front_left")
		self.assertIs(angle, chosen)
		self.assertTrue(supported)


class TestHeroAngleSurvivesImport(TestCase):
	def test_a_chosen_angle_is_read_back_from_the_product_shot_text(self):
		from joymedia.services.planning.creative import normalize_product_hero_edges
		from joymedia.services.planning.product_views import requested_product_view_for_scene

		scenes = [
			{"product_view": "front_right", "duration_seconds": 2.5},
			{"cast": ["m"], "duration_seconds": 3},
			{"product_view": "source", "duration_seconds": 3},
		]
		normalize_product_hero_edges(
			{"scenes": scenes}, {"product_hero_structure": True, "hero_product": "product"}
		)
		# The imported storyboard keeps only the text, as for CRB-00127.
		imported = {"visual_camera": scenes[0]["visual_camera"], "product_view": None}
		self.assertEqual("front_right", requested_product_view_for_scene(imported))
		self.assertEqual(
			"source", requested_product_view_for_scene({"visual_camera": scenes[2]["visual_camera"]})
		)
