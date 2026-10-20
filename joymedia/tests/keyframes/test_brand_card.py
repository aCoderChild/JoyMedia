import io
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from joymedia.services.editing.composer import hold_brand_card
from joymedia.services.keyframes.overlay import closing_subjects, composite_subjects, layout


class TestBrandCard(FrappeTestCase):
	def test_guided_drawn_hero_keeps_integrated_scene_without_an_opaque_actor_card(self):
		from joymedia.services.keyframes.overlay import paste_subjects_into_keyframe

		shot = {
			"shot": "S",
			"shot_number": 1,
			"character_mode": "Draw in scene",
			"reference_retention": {"workflow": "W"},
			"references": [
				{"reference_role": "Character", "asset_version": "ACTOR"},
				{
					"reference_role": "Product",
					"asset_version": "PACK",
					"preservation_mode": "reference_guided",
				},
			],
		}
		with (
			patch.object(
				frappe.db,
				"get_value",
				side_effect=[
					frappe._dict(generation_task="T"),
					("S", "R"),
					frappe.as_json({"shots": [shot]}),
				],
			),
			patch("joymedia.services.keyframes.overlay.closing_subjects") as collage,
		):
			self.assertEqual(
				b"integrated-scene",
				paste_subjects_into_keyframe(frappe._dict(name="A"), b"integrated-scene", {}),
			)
		collage.assert_not_called()

	def test_drawn_closing_scene_uses_measured_retention_instead_of_photo_cells(self):
		from joymedia.services.keyframes.overlay import paste_subjects_into_keyframe

		shot = {
			"shot": "S",
			"shot_number": 1,
			"character_mode": "Draw in scene",
			"reference_retention": {"workflow": "W"},
			"references": [
				{"reference_role": "Character", "asset_version": "ACTOR"},
				{"reference_role": "Product", "asset_version": "PACK"},
			],
		}
		snapshot = {"shots": [shot]}
		with (
			patch.object(
				frappe.db,
				"get_value",
				side_effect=[frappe._dict(generation_task="T"), ("S", "R"), frappe.as_json(snapshot)],
			),
			patch("joymedia.services.consistency.retention.retain", return_value=b"grounded-scene") as retain,
			patch("joymedia.services.keyframes.overlay.composite_subjects") as collage,
		):
			self.assertEqual(
				b"grounded-scene", paste_subjects_into_keyframe(frappe._dict(name="A"), b"scene", {})
			)
		retain.assert_called_once()
		collage.assert_not_called()

	def test_jpeg_references_are_kept_on_the_closing_card(self):
		with (
			patch("joymedia.services.keyframes.overlay._cutout_path", return_value=None),
			patch("joymedia.services.keyframes.overlay._any_image_path", return_value="/source.jpg"),
		):
			subjects = closing_subjects([{"reference_role": "Product", "asset_version": "AV1"}])
		self.assertEqual(
			[{"role": "product", "asset_version": "AV1", "path": "/source.jpg", "opaque": True}], subjects
		)

	def test_product_print_is_not_tinted_to_the_room(self):
		with tempfile.TemporaryDirectory() as folder:
			pack = Path(folder) / "pack.png"
			Image.new("RGBA", (100, 60), (20, 100, 220, 255)).save(pack)
			background = io.BytesIO()
			Image.new("RGB", (320, 560), (255, 0, 0)).save(background, "PNG")
			content = composite_subjects(
				background.getvalue(), [{"role": "product", "path": str(pack), "opaque": True}], hero=True
			)
			image = Image.open(io.BytesIO(content))
			x, y, width, height = layout((320, 560), [("product", 100, 60)], product_hero=True)[0]
			self.assertEqual((20, 100, 220), image.getpixel((x + width // 2, y + height // 2)))
			self.assertEqual((255, 255, 255), image.getpixel((0, 0)))

	def test_last_two_seconds_use_the_brand_card_without_changing_frame_count(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			video, card, output = root / "input.mp4", root / "card.png", root / "held.mp4"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-f",
					"lavfi",
					"-i",
					"color=c=blue:s=64x64:r=24:d=4",
					"-c:v",
					"libx264",
					"-pix_fmt",
					"yuv420p",
					str(video),
				],
				check=True,
				capture_output=True,
			)
			Image.new("RGB", (64, 64), (255, 0, 0)).save(card)
			hold_brand_card(video, card, output, {"fps": 24, "width": 64, "height": 64}, 96)
			raw = subprocess.run(
				["ffmpeg", "-v", "error", "-i", str(output), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
				check=True,
				capture_output=True,
			).stdout
			stride = 64 * 64 * 3
			self.assertEqual(96 * stride, len(raw))
			self.assertGreater(raw[2], raw[0])  # opening is still the blue video
			for index in range(48, 96):
				pixel = raw[index * stride : index * stride + 3]
				self.assertGreater(pixel[0], 240)
				self.assertLess(pixel[2], 15)

	def test_hero_photos_have_disjoint_cells_for_portrait_square_and_landscape(self):
		for canvas in [(720, 1280), (1280, 720), (720, 720)]:
			for cast in range(1, 5):
				for products in range(1, 5):
					sizes = [("character", 1254, 1254)] * cast + [("product", 1586, 992)] * products
					boxes = layout(canvas, sizes, product_hero=True)
					for i, (x, y, w, h) in enumerate(boxes):
						self.assertTrue(0 <= x < x + w <= canvas[0])
						self.assertTrue(0 <= y < y + h <= canvas[1])
						self.assertLess(abs(w / h - sizes[i][1] / sizes[i][2]), 0.06)
						for xx, yy, ww, hh in boxes[:i]:
							self.assertFalse(x < xx + ww and xx < x + w and y < yy + hh and yy < y + h)

	def test_required_closing_card_missing_its_source_cannot_fall_back_to_generated_art(self):
		from joymedia.services.editing.composer import _closing_hold_source

		with (
			patch("frappe.db.get_value", return_value='{"shots":[{"shot":"S","closing_hold_seconds":5}]}'),
			patch("frappe.get_all", return_value=[]),
		):
			with self.assertRaisesRegex(ValueError, "required closing artwork"):
				_closing_hold_source("R", "S")

	def test_full_card_uses_its_source_without_testing_discarded_generated_pack(self):
		from joymedia.services.editing.composer import _with_locked_product

		with (
			patch("joymedia.services.editing.composer._closing_hold_source", return_value=(5, "/frozen.png")),
			patch("joymedia.services.editing.composer.product_lock_for") as lock,
		):
			path = Path("/clip.mp4")
			self.assertEqual(
				path, _with_locked_product(path, "R", frappe._dict(name="S"), [], {"fps": 24}, 120)
			)
			lock.assert_not_called()

	def test_partial_card_still_requires_package_protection_before_the_hold(self):
		from joymedia.services.editing.composer import _with_locked_product

		with (
			patch("joymedia.services.editing.composer._closing_hold_source", return_value=(2, "/frozen.png")),
			patch("joymedia.services.editing.composer.product_lock_for", return_value=None) as lock,
		):
			path = Path("/clip.mp4")
			self.assertEqual(
				path, _with_locked_product(path, "R", frappe._dict(name="S"), [], {"fps": 24}, 120)
			)
			lock.assert_called_once()

	def test_in_run_generated_artwork_is_resolved_from_the_video_dependency(self):
		from types import SimpleNamespace

		from joymedia.services.editing.composer import _closing_hold_source

		with tempfile.TemporaryDirectory() as folder:
			image = Path(folder) / "card.png"
			Image.new("RGB", (32, 32), "white").save(image)

			def value(doctype, name, field, **kwargs):
				if doctype == "Generation Run":
					return '{"shots":[{"shot":"S","closing_hold_seconds":5}]}'
				if doctype == "Generation Workflow":
					return "Video"
				if doctype == "Generation Attempt":
					self.assertEqual(name["generation_task"], "FROZEN-IMAGE-TASK")
					return "IMAGE-ATTEMPT"
				if doctype == "Generation Artifact":
					return "IMAGE-ARTIFACT" if isinstance(name, dict) else "/private/card.png"
				self.fail(f"Unexpected mutable source lookup: {doctype}")

			video = frappe._dict(
				name="VIDEO-TASK",
				workflow="WF",
				depends_on_task="FROZEN-IMAGE-TASK",
				dependency_artifact_role="Primary Image",
			)
			with (
				patch("frappe.db.get_value", side_effect=value),
				patch("frappe.get_all", return_value=[video]),
				patch("frappe.get_doc", return_value=SimpleNamespace(get_full_path=lambda: str(image))),
			):
				self.assertEqual(_closing_hold_source("RUN", "S"), (5, str(image)))
