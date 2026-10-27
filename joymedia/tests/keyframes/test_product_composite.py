import hashlib
from io import BytesIO
from unittest import TestCase

from PIL import Image, ImageDraw

from joymedia.services.keyframes.product_composite import compose_product_on_surface, projected_product_box


class TestProductComposite(TestCase):
	def setUp(self):
		background = Image.new("RGB", (400, 300), (170, 140, 110))
		output = BytesIO()
		background.save(output, "PNG")
		self.background = output.getvalue()
		cutout = Image.new("RGBA", (100, 60), (0, 0, 0, 0))
		ImageDraw.Draw(cutout).rectangle((5, 5, 94, 54), fill=(40, 150, 230, 255))
		output = BytesIO()
		cutout.save(output, "PNG")
		self.cutout = output.getvalue()
		self.surface = {
			"background_sha256": hashlib.sha256(self.background).hexdigest(),
			"polygon": [[0.05, 0.4], [0.95, 0.4], [0.95, 0.85], [0.05, 0.85]],
		}

	def test_composes_supported_product_and_records_evidence(self):
		content, proof = compose_product_on_surface(
			self.background, self.cutout, [0.2, 0.4, 0.5, 0.35], self.surface
		)
		self.assertEqual("surface_contact_2d", proof["kind"])
		self.assertEqual(5, len(proof["contact_points"]))
		self.assertEqual((400, 300), Image.open(BytesIO(content)).size)

	def test_rejects_floating_product_or_wrong_background(self):
		with self.assertRaisesRegex(ValueError, "outside its supporting surface"):
			compose_product_on_surface(self.background, self.cutout, [0.2, 0.02, 0.5, 0.2], self.surface)
		with self.assertRaisesRegex(ValueError, "different frame"):
			compose_product_on_surface(
				self.background,
				self.cutout,
				[0.2, 0.4, 0.5, 0.35],
				{**self.surface, "background_sha256": "0" * 64},
			)

	def test_rejects_opaque_photo_panel(self):
		opaque = Image.new("RGB", (100, 60), "white")
		output = BytesIO()
		opaque.save(output, "PNG")
		with self.assertRaisesRegex(ValueError, "transparent RGBA"):
			compose_product_on_surface(
				self.background, output.getvalue(), [0.2, 0.4, 0.5, 0.35], self.surface
			)

	def test_projective_scale_changes_with_table_depth(self):
		table = [[0.2, 0.2], [0.8, 0.2], [1, 0.9], [0, 0.9]]
		back, _ = projected_product_box(
			(400, 300),
			(100, 60),
			{
				"table_quad": table,
				"anchor": [0.5, 0.2],
				"width_fraction": 0.25,
			},
		)
		front, proof = projected_product_box(
			(400, 300),
			(100, 60),
			{
				"table_quad": table,
				"anchor": [0.5, 0.8],
				"width_fraction": 0.25,
			},
		)
		self.assertGreater(front[2], back[2])
		self.assertEqual("table_projective_scale", proof["kind"])

	def test_projective_scale_rejects_off_table_width(self):
		with self.assertRaisesRegex(ValueError, "extends beyond"):
			projected_product_box(
				(400, 300),
				(100, 60),
				{
					"table_quad": [[0, 0], [1, 0], [1, 1], [0, 1]],
					"anchor": [0.9, 0.5],
					"width_fraction": 0.3,
				},
			)

	def test_measured_scale_must_agree_with_projected_fraction(self):
		placement = {
			"table_quad": [[0.05, 0.4], [0.95, 0.4], [0.95, 0.85], [0.05, 0.85]],
			"anchor": [0.5, 0.6],
			"scale_evidence": {"product_width_mm": 200, "support_width_mm": 800},
		}
		_, proof = projected_product_box((400, 300), (100, 60), placement)
		self.assertEqual(200, proof["scale_evidence"]["product_width_mm"])
		self.assertEqual(0.25, proof["width_fraction"])
		placement["width_fraction"] = 0.25
		placement["scale_evidence"]["support_width_mm"] = 1200
		with self.assertRaisesRegex(ValueError, "conflicts"):
			projected_product_box((400, 300), (100, 60), placement)

	def test_compositor_sizes_from_table_without_manual_pixel_box(self):
		content, proof = compose_product_on_surface(
			self.background,
			self.cutout,
			None,
			{
				**self.surface,
				"placement": {
					"table_quad": [[0.05, 0.4], [0.95, 0.4], [0.95, 0.85], [0.05, 0.85]],
					"anchor": [0.5, 0.6],
					"width_fraction": 0.25,
				},
			},
		)
		self.assertLess(proof["box_pixels"][2], 150)
		self.assertEqual("table_projective_scale", proof["geometry"]["kind"])
		self.assertEqual((400, 300), Image.open(BytesIO(content)).size)
