import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from joymedia.services import subject_overlay
from joymedia.services.subject_overlay import composite_subjects, layout, pasted_references


class TestLayout(FrappeTestCase):
	def test_every_subject_keeps_its_aspect_ratio_and_stays_inside_the_canvas(self):
		for canvas in ((720, 1280), (1280, 720), (1000, 1000)):
			sizes = [("character", 464, 560), ("product", 300, 420), ("logo", 600, 150), ("product", 900, 200)]
			for (role, width, height), (x, y, box_width, box_height) in zip(sizes, layout(canvas, sizes)):
				# Pixel rounding only: each side is within one pixel of the exact proportional size.
				self.assertLessEqual(abs(box_height - box_width * height / width), 1, f"{role} on {canvas}")
				self.assertGreaterEqual(x, 0)
				self.assertGreaterEqual(y, 0)
				self.assertLessEqual(x + box_width, canvas[0])
				self.assertLessEqual(y + box_height, canvas[1])

	def test_a_product_stands_beside_the_character_on_the_same_floor(self):
		character, product = layout((720, 1280), [("character", 464, 560), ("product", 1076, 717)])
		self.assertGreater(product[0] + product[2] / 2, character[0] + character[2] / 2)
		self.assertLessEqual(abs((product[1] + product[3]) - (character[1] + character[3])), 0.05 * 1280)
		self.assertLess(product[3], character[3])

	def test_a_smaller_character_is_drawn_smaller_with_the_same_proportions(self):
		mother, baby = layout((720, 1280), [("character", 464, 560, 1), ("character", 464, 560, 0.5)])
		self.assertLessEqual(baby[3], 0.55 * mother[3])
		self.assertLessEqual(abs(baby[2] / baby[3] - mother[2] / mother[3]), 0.02)

	def test_several_products_stand_together_in_the_middle(self):
		boxes = layout((720, 1280), [("character", 464, 560)] + [("product", 1076, 717)] * 3)[1:]
		for left, right in zip(boxes, boxes[1:]):
			self.assertLess(right[0], left[0] + left[2])  # each overlaps its neighbour a little
		centre = sum(x + w / 2 for x, _y, w, _h in boxes) / 3
		self.assertAlmostEqual(360, centre, delta=40)
		for x, y, w, h in boxes:
			self.assertGreaterEqual(x, 0)
			self.assertLessEqual(x + w, 720)

	def test_a_lone_small_character_fills_the_frame_like_a_lone_large_one(self):
		alone = layout((720, 1280), [("character", 464, 560, 0.5)])[0]
		normal = layout((720, 1280), [("character", 464, 560, 1)])[0]
		self.assertEqual(normal[2:], alone[2:])

	def test_every_role_accepts_a_size_entry(self):
		boxes = layout((720, 1280), [("character", 464, 560, 1), ("product", 1076, 717, 1), ("logo", 600, 150, 1)])
		self.assertTrue(all(box is not None for box in boxes))

	def test_a_lone_product_is_the_hero_and_much_larger_than_one_beside_a_character(self):
		alone = layout((1280, 720), [("product", 420, 560)])[0]
		beside = layout((1280, 720), [("character", 464, 560), ("product", 420, 560)])[1]
		self.assertGreater(alone[3], 2 * beside[3])
		self.assertLessEqual(abs(alone[2] / alone[3] - 420 / 560), 0.02)

	def test_logos_sit_in_opposite_top_corners(self):
		first, second = layout((1000, 1000), [("logo", 200, 100), ("logo", 200, 100)])
		self.assertLess(first[0], 500)
		self.assertGreater(second[0], 500)
		self.assertEqual(first[1], second[1])


class TestComposite(FrappeTestCase):
	def _png(self, mode, size, color):
		output = io.BytesIO()
		Image.new(mode, size, color).save(output, "PNG")
		return output.getvalue()

	def test_the_real_pixels_are_pasted_and_transparent_areas_show_the_background(self):
		with tempfile.TemporaryDirectory() as folder:
			asset = Image.new("RGBA", (200, 300), (255, 0, 0, 255))
			for x in range(100):
				for y in range(100):
					asset.putpixel((x, y), (0, 0, 0, 0))
			path = Path(folder) / "asset.png"
			asset.save(path)
			result = Image.open(io.BytesIO(composite_subjects(
				self._png("RGB", (400, 800), (0, 0, 255)), [{"role": "character", "path": str(path)}]
			))).convert("RGB")
			x, y, width, height = layout((400, 800), [("character", 200, 300)])[0]
			self.assertEqual(result.size, (400, 800))
			# Pasted pixels keep the asset's colour apart from a slight match to the room.
			self.assertLess(sum(abs(a - b) for a, b in zip((255, 0, 0), result.getpixel((x + width - 5, y + height // 2)))), 90)
			self.assertEqual((0, 0, 255), result.getpixel((x + 2, y + 2)))


class TestPastedReferences(FrappeTestCase):
	def test_only_cutouts_of_pasteable_roles_are_pasted(self):
		paths = {"AV1": "/a.png", "AV2": None, "AV3": "/c.png"}
		references = [
			{"reference_role": "Character", "asset_version": "AV1"},
			{"reference_role": "Product", "asset_version": "AV2"},
			{"reference_role": "Environment", "asset_version": "AV3"},
			{"reference_role": "Logo", "asset_version": "AV3"},
		]
		with patch.object(subject_overlay, "_cutout_path", side_effect=paths.get):
			self.assertEqual(["character", "logo"], [p["role"] for p in pasted_references(references)])

	def test_the_keyframe_prompt_asks_for_an_empty_setting_only_when_something_is_pasted(self):
		from joymedia.services.prompt_compiler import compile_prompt_for_documents

		shot = frappe._dict(
			name="S", shot_number=1, image_prompt="A room with a hand.", setting_prompt="A bright room.", generation_prompt="A room.",
			references=[{"reference_role": "Character", "asset_version": "AV1"}],
		)
		with patch.object(subject_overlay, "_cutout_path", return_value="/a.png"):
			prompt = compile_prompt_for_documents(shot, {}, prompt_source="image")
			self.assertIn(subject_overlay.EMPTY_SETTING, prompt)
			self.assertNotIn("hand", prompt.split(subject_overlay.EMPTY_SETTING)[0])
		shot.setting_prompt = ""
		with patch.object(subject_overlay, "_cutout_path", return_value="/a.png"):
			self.assertIn(subject_overlay.DEFAULT_SETTING, compile_prompt_for_documents(shot, {}, prompt_source="image"))
		with patch.object(subject_overlay, "_cutout_path", return_value=None):
			self.assertNotIn(subject_overlay.EMPTY_SETTING, compile_prompt_for_documents(shot, {}, prompt_source="image"))


class TestKeyframeIngest(FrappeTestCase):
	def test_the_run_snapshot_decides_what_is_pasted(self):
		snapshot = {"shots": [{"shot": "S1", "references": [{"reference_role": "character", "asset_version": "AV1"}]}]}
		values = {
			("Generation Attempt", "ATT"): frappe._dict(generation_task="TASK"),
			("Generation Task", "TASK"): ("S1", "RUN"),
			("Generation Run", "RUN"): frappe.as_json(snapshot),
		}
		with patch.object(frappe.db, "get_value", side_effect=lambda doctype, name, *a, **k: values[(doctype, name)]), patch.object(
			subject_overlay, "_cutout_path", return_value="/a.png"
		), patch.object(subject_overlay, "composite_subjects", return_value=b"done") as composite:
			result = subject_overlay.paste_subjects_into_keyframe(frappe._dict(name="ATT"), b"raw")
		self.assertEqual(b"done", result)
		self.assertEqual("character", composite.call_args.args[1][0]["role"])

	def test_a_shot_without_cutouts_is_left_untouched(self):
		with patch.object(frappe.db, "get_value", side_effect=[frappe._dict(generation_task="T"), ("S1", "R"), "{}"]):
			self.assertEqual(b"raw", subject_overlay.paste_subjects_into_keyframe(frappe._dict(name="A"), b"raw"))

	def test_pasted_references_are_not_inputs_of_the_image_stage(self):
		from joymedia.services.generation_orchestrator import _pipeline_reference_inputs

		workflow = frappe._dict(name="W")
		contract = [{"role": "product", "max_count": 1, "accepted_media_type": "Image", "allow_multiple": False}]
		references = frappe._dict(character_mode="Paste exact art", references=[
			{"reference_role": "Product", "asset_version": "AV1"}, {"reference_role": "Logo", "asset_version": "AV2"},
			{"reference_role": "Product", "asset_version": "AV3"},
		])
		with patch("joymedia.services.workflow_resolver.get_workflow_input_contract", return_value=contract), patch.object(
			subject_overlay, "_cutout_path", side_effect=lambda av: "/x.png" if av == "AV1" else None
		):
			self.assertEqual({"product": ["AV3"]}, _pipeline_reference_inputs(references, workflow))


class TestUsableSetting(FrappeTestCase):
	def test_a_setting_that_names_a_subject_is_replaced_by_the_default(self):
		self.assertEqual(subject_overlay.DEFAULT_SETTING, subject_overlay.usable_setting("Macro close-up on hand pulling tissue."))
		self.assertEqual(subject_overlay.DEFAULT_SETTING, subject_overlay.usable_setting(""))
		self.assertEqual("A warm kitchen with window light.", subject_overlay.usable_setting("A warm kitchen with window light."))


class TestDescribeColours(FrappeTestCase):
	def test_the_main_colours_are_named_and_transparency_is_ignored(self):
		with tempfile.TemporaryDirectory() as folder:
			image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
			for x in range(40):
				for y in range(40):
					if y < 30:
						image.putpixel((x, y), (240, 225, 200, 255))
					elif y < 36:
						image.putpixel((x, y), (120, 80, 50, 255))
			path = Path(folder) / "a.png"
			image.save(path)
			subject_overlay.describe_colours.cache_clear()
			with patch.object(frappe.db, "get_value", return_value="/f.png"), patch.object(
				frappe, "get_doc", return_value=frappe._dict(get_full_path=lambda: str(path))
			):
				self.assertEqual("mostly cream, with brown details", subject_overlay.describe_colours("AV-COLOUR"))


class TestCharacterMode(FrappeTestCase):
	def test_characters_are_pasted_only_in_paste_mode_but_products_and_logos_always(self):
		references = [
			{"reference_role": "Character", "asset_version": "AV1"}, {"reference_role": "Product", "asset_version": "AV2"},
			{"reference_role": "Logo", "asset_version": "AV3"},
		]
		with patch.object(subject_overlay, "_cutout_path", return_value="/a.png"):
			self.assertEqual(["character", "product", "logo"], [p["role"] for p in pasted_references(references, "Paste exact art")])
			self.assertEqual(["product", "logo"], [p["role"] for p in pasted_references(references, "Draw in scene")])

	def test_the_character_board_keeps_each_picture_uncropped_and_the_mother_larger(self):
		with tempfile.TemporaryDirectory() as folder:
			mother, kid = Path(folder) / "m.png", Path(folder) / "k.png"
			Image.new("RGBA", (200, 300), (250, 240, 230, 255)).save(mother)
			Image.new("RGBA", (200, 300), (250, 240, 230, 255)).save(kid)
			paths = {"AVM": str(mother), "AVK": str(kid)}
			references = [{"reference_role": "Character", "asset_version": "AVM"}, {"reference_role": "Character", "asset_version": "AVK"}]
			with patch.object(subject_overlay, "_any_image_path", side_effect=paths.get), patch.object(
				frappe, "get_site_path", return_value=folder
			):
				board = subject_overlay.character_board(references, {"AVM": 1, "AVK": 0.5})
			image = Image.open(board)
			self.assertEqual(768, image.height)
			# The mother's tile is twice as tall as the kid's, both from the same baseline.
			column = lambda x: [y for y in range(image.height) if image.getpixel((x, y)) != (236, 232, 226)]
			mother_x, kid_x = 40 + 60, image.width - 40 - 30
			self.assertGreater(len(column(mother_x)), 1.8 * len(column(kid_x)))



class TestEmptierSide(FrappeTestCase):
	def test_the_product_goes_to_the_side_of_the_floor_with_less_detail(self):
		from PIL import ImageDraw

		image = Image.new("RGBA", (400, 800), (200, 190, 170, 255))
		draw = ImageDraw.Draw(image)
		for x in range(0, 200, 6):  # detail (a figure) on the left half of the floor
			draw.line([(x, 500), (x, 780)], fill=(40, 30, 20, 255), width=2)
		self.assertEqual(0.73, subject_overlay._emptier_side(image))
		mirrored = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
		self.assertEqual(0.27, subject_overlay._emptier_side(mirrored))


class TestTuning(FrappeTestCase):
	def test_a_site_can_override_a_tunable_and_unknown_keys_are_ignored(self):
		from joymedia.services.tuning import DEFAULTS, tune

		self.assertEqual(DEFAULTS["character_height"], tune("character_height"))
		with patch.object(frappe, "conf", frappe._dict(joymedia_tuning={"character_height": 0.5, "nonsense": 1})):
			self.assertEqual(0.5, tune("character_height"))
			self.assertEqual(DEFAULTS["product_height"], tune("product_height"))
		small = layout((720, 1280), [("character", 464, 560)])[0]
		with patch.object(frappe, "conf", frappe._dict(joymedia_tuning={"character_height": 0.5})):
			large = layout((720, 1280), [("character", 464, 560)])[0]
		self.assertGreater(large[3], small[3])


class TestDrawnProduct(FrappeTestCase):
	def test_with_drawn_characters_the_product_is_small_and_in_the_clear_corner(self):
		normal = layout((720, 1280), [("character", 464, 560), ("product", 1076, 717)])[1]
		corner = layout((720, 1280), [("product", 1076, 717)], drawn=True)[0]
		self.assertLess(corner[3], normal[3])
		self.assertGreater(corner[0] + corner[2] / 2, 0.7 * 720)
		self.assertGreater(corner[1] + corner[3], 0.9 * 1280)
		self.assertLessEqual(abs(corner[2] / corner[3] - 1076 / 717), 0.02)

	def test_the_prompt_keeps_that_corner_clear_only_when_a_product_will_be_pasted(self):
		from joymedia.services.prompt_compiler import _clear_corner_note

		shot = frappe._dict(references=[{"reference_role": "Product", "asset_version": "AV1"}])
		with patch.object(subject_overlay, "_cutout_path", return_value="/p.png"):
			self.assertIn("Keep the bottom-right corner of the floor clear", _clear_corner_note(shot))
		with patch.object(subject_overlay, "_cutout_path", return_value=None):
			self.assertEqual("", _clear_corner_note(shot))
