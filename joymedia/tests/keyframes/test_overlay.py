import io
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from joymedia.services.keyframes import overlay as subject_overlay
from joymedia.services.keyframes.overlay import composite_subjects, layout, pasted_references


class TestLayout(FrappeTestCase):
	def test_every_subject_keeps_its_aspect_ratio_and_stays_inside_the_canvas(self):
		for canvas in ((720, 1280), (1280, 720), (1000, 1000)):
			sizes = [("character", 464, 560), ("product", 300, 420), ("product", 900, 200)]
			for (role, width, height), (x, y, box_width, box_height) in zip(
				sizes, layout(canvas, sizes), strict=False
			):
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
		for left, right in itertools.pairwise(boxes):
			self.assertLess(right[0], left[0] + left[2])  # each overlaps its neighbour a little
		centre = sum(x + w / 2 for x, _y, w, _h in boxes) / 3
		self.assertAlmostEqual(360, centre, delta=40)
		for x, _y, w, _h in boxes:
			self.assertGreaterEqual(x, 0)
			self.assertLessEqual(x + w, 720)

	def test_a_lone_small_character_fills_the_frame_like_a_lone_large_one(self):
		alone = layout((720, 1280), [("character", 464, 560, 0.5)])[0]
		normal = layout((720, 1280), [("character", 464, 560, 1)])[0]
		self.assertEqual(normal[2:], alone[2:])

	def test_every_role_accepts_a_size_entry(self):
		boxes = layout((720, 1280), [("character", 464, 560, 1), ("product", 1076, 717, 1)])
		self.assertTrue(all(box is not None for box in boxes))

	def test_a_lone_product_is_the_hero_and_much_larger_than_one_beside_a_character(self):
		alone = layout((1280, 720), [("product", 420, 560)])[0]
		beside = layout((1280, 720), [("character", 464, 560), ("product", 420, 560)])[1]
		self.assertGreater(alone[3], 2 * beside[3])
		self.assertLessEqual(abs(alone[2] / alone[3] - 420 / 560), 0.02)


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
			result = Image.open(
				io.BytesIO(
					composite_subjects(
						self._png("RGB", (400, 800), (0, 0, 255)), [{"role": "character", "path": str(path)}]
					)
				)
			).convert("RGB")
			x, y, width, height = layout((400, 800), [("character", 200, 300)])[0]
			self.assertEqual(result.size, (400, 800))
			# Pasted pixels keep the asset's colour apart from a slight match to the room.
			self.assertLess(
				sum(
					abs(a - b)
					for a, b in zip(
						(255, 0, 0), result.getpixel((x + width - 5, y + height // 2)), strict=False
					)
				),
				90,
			)
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
			# Logos are laid over the finished film instead (the video model warps a logo drawn into a frame).
			self.assertEqual(["character"], [p["role"] for p in pasted_references(references)])

	def test_the_keyframe_prompt_asks_for_an_empty_setting_only_when_something_is_pasted(self):
		from joymedia.services.planning.prompts import compile_prompt_for_documents

		shot = frappe._dict(
			name="S",
			shot_number=1,
			image_prompt="A room with a hand.",
			setting_prompt="A bright room.",
			generation_prompt="A room.",
			references=[{"reference_role": "Character", "asset_version": "AV1"}],
		)
		with patch.object(subject_overlay, "_cutout_path", return_value="/a.png"):
			prompt = compile_prompt_for_documents(shot, {}, prompt_source="image")
			self.assertIn(subject_overlay.EMPTY_SETTING, prompt)
			self.assertNotIn("hand", prompt.split(subject_overlay.EMPTY_SETTING)[0])
		shot.setting_prompt = ""
		with patch.object(subject_overlay, "_cutout_path", return_value="/a.png"):
			self.assertIn(
				subject_overlay.DEFAULT_SETTING, compile_prompt_for_documents(shot, {}, prompt_source="image")
			)
		with patch.object(subject_overlay, "_cutout_path", return_value=None):
			self.assertNotIn(
				subject_overlay.EMPTY_SETTING, compile_prompt_for_documents(shot, {}, prompt_source="image")
			)


class TestKeyframeIngest(FrappeTestCase):
	def test_the_run_snapshot_decides_what_is_pasted(self):
		snapshot = {
			"shots": [{"shot": "S1", "references": [{"reference_role": "character", "asset_version": "AV1"}]}]
		}
		values = {
			("Generation Attempt", "ATT"): frappe._dict(generation_task="TASK"),
			("Generation Task", "TASK"): ("S1", "RUN"),
			("Generation Run", "RUN"): frappe.as_json(snapshot),
		}
		with (
			patch.object(
				frappe.db, "get_value", side_effect=lambda doctype, name, *a, **k: values[(doctype, name)]
			),
			patch.object(subject_overlay, "_cutout_path", return_value="/a.png"),
			patch.object(subject_overlay, "composite_subjects", return_value=b"done") as composite,
		):
			result = subject_overlay.paste_subjects_into_keyframe(frappe._dict(name="ATT"), b"raw")
		self.assertEqual(b"done", result)
		self.assertEqual("character", composite.call_args.args[1][0]["role"])

	def test_a_shot_without_cutouts_is_left_untouched(self):
		with patch.object(
			frappe.db, "get_value", side_effect=[frappe._dict(generation_task="T"), ("S1", "R"), "{}"]
		):
			self.assertEqual(
				b"raw", subject_overlay.paste_subjects_into_keyframe(frappe._dict(name="A"), b"raw")
			)

	def test_pasted_references_are_not_inputs_of_the_image_stage(self):
		from joymedia.services.generation.orchestrator import _pipeline_reference_inputs

		workflow = frappe._dict(name="W")
		contract = [
			{"role": "product", "max_count": 1, "accepted_media_type": "Image", "allow_multiple": False}
		]
		references = frappe._dict(
			character_mode="Paste exact art",
			references=[
				{"reference_role": "Product", "asset_version": "AV1"},
				{"reference_role": "Logo", "asset_version": "AV2"},
				{"reference_role": "Product", "asset_version": "AV3"},
			],
		)
		with (
			patch("joymedia.services.workflows.resolver.get_workflow_input_contract", return_value=contract),
			patch.object(
				subject_overlay, "_cutout_path", side_effect=lambda av: "/x.png" if av == "AV1" else None
			),
		):
			self.assertEqual({"product": ["AV3"]}, _pipeline_reference_inputs(references, workflow))


class TestUsableSetting(FrappeTestCase):
	def test_a_setting_that_names_a_subject_is_replaced_by_the_default(self):
		self.assertEqual(
			subject_overlay.DEFAULT_SETTING,
			subject_overlay.usable_setting("Macro close-up on hand pulling tissue."),
		)
		self.assertEqual(subject_overlay.DEFAULT_SETTING, subject_overlay.usable_setting(""))
		self.assertEqual(
			"A warm kitchen with window light.",
			subject_overlay.usable_setting("A warm kitchen with window light."),
		)


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
			with (
				patch.object(frappe.db, "get_value", return_value="/f.png"),
				patch.object(frappe, "get_doc", return_value=frappe._dict(get_full_path=lambda: str(path))),
			):
				self.assertEqual(
					"mostly cream, with brown details", subject_overlay.describe_colours("AV-COLOUR")
				)


class TestCharacterMode(FrappeTestCase):
	def test_the_real_product_pack_is_always_pasted_and_characters_only_in_paste_mode(self):
		references = [
			{"reference_role": "Character", "asset_version": "AV1"},
			{"reference_role": "Product", "asset_version": "AV2"},
			{"reference_role": "Logo", "asset_version": "AV3"},
		]
		with patch.object(subject_overlay, "_cutout_path", return_value="/a.png"):
			self.assertEqual(
				["character", "product"],
				[p["role"] for p in pasted_references(references, "Paste exact art")],
			)
			self.assertEqual(["product"], [p["role"] for p in pasted_references(references, "Draw in scene")])

	def test_the_character_board_keeps_each_picture_uncropped_and_the_mother_larger(self):
		with tempfile.TemporaryDirectory() as folder:
			mother, kid = Path(folder) / "m.png", Path(folder) / "k.png"
			Image.new("RGBA", (200, 300), (250, 240, 230, 255)).save(mother)
			Image.new("RGBA", (200, 300), (250, 240, 230, 255)).save(kid)
			paths = {"AVM": str(mother), "AVK": str(kid)}
			references = [
				{"reference_role": "Character", "asset_version": "AVM"},
				{"reference_role": "Character", "asset_version": "AVK"},
			]
			with (
				patch.object(subject_overlay, "_any_image_path", side_effect=paths.get),
				patch.object(frappe, "get_site_path", return_value=folder),
			):
				board = subject_overlay.character_board(references, {"AVM": 1, "AVK": 0.5})
			image = Image.open(board)
			self.assertEqual(768, image.height)

			# The mother's tile is twice as tall as the kid's, both from the same baseline.
			def column(x):
				return [y for y in range(image.height) if image.getpixel((x, y)) != (236, 232, 226)]

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
		from joymedia.services.project.tuning import DEFAULTS, tune

		self.assertEqual(DEFAULTS["character_height"], tune("character_height"))
		with patch.object(
			frappe, "conf", frappe._dict(joymedia_tuning={"character_height": 0.5, "nonsense": 1})
		):
			self.assertEqual(0.5, tune("character_height"))
			self.assertEqual(DEFAULTS["product_height"], tune("product_height"))
		small = layout((720, 1280), [("character", 464, 560)])[0]
		with patch.object(frappe, "conf", frappe._dict(joymedia_tuning={"character_height": 0.5})):
			large = layout((720, 1280), [("character", 464, 560)])[0]
		self.assertGreater(large[3], small[3])


class TestProductPlacement(FrappeTestCase):
	def test_on_the_closing_scene_the_product_is_large_in_the_centre_and_the_cast_at_the_sides(self):
		canvas = (720, 1280)
		mother, kid, product = layout(
			canvas,
			[("character", 464, 560, 1), ("character", 464, 560, 0.55), ("product", 1076, 717, 1)],
			product_hero=True,
		)
		self.assertAlmostEqual(0.5 * canvas[0], product[0] + product[2] / 2, delta=2)
		normal = layout(canvas, [("character", 464, 560), ("product", 1076, 717)])[1]
		self.assertGreater(product[3], 1.5 * normal[3])
		self.assertGreater(product[2], mother[2])  # wider than any character, centred and painted in front
		self.assertLess(mother[0] + mother[2] / 2, product[0] + product[2] / 2)
		self.assertGreater(kid[0] + kid[2] / 2, product[0] + product[2] / 2)
		self.assertLess(kid[3], mother[3])  # the child stays smaller

	def test_the_closing_scene_is_the_last_one_of_the_film(self):
		from joymedia.services.keyframes.overlay import closes_film

		project = {"shots": [{"shot_number": 1}, {"shot_number": 2}, {"shot_number": 3}]}
		self.assertTrue(closes_film({"shot_number": 3}, project))
		self.assertFalse(closes_film({"shot_number": 2}, project))
		self.assertFalse(closes_film({"shot_number": 0}, project))

	def test_in_front_of_drawn_characters_the_pack_stands_in_the_lower_middle_at_an_everyday_size(self):
		canvas = (720, 1280)
		front = layout(canvas, [("product", 1076, 717)], front=True)[0]
		closing = layout(canvas, [("product", 1076, 717)], product_hero=True)[0]
		self.assertAlmostEqual(360, front[0] + front[2] / 2, delta=2)
		self.assertGreater(front[1] + front[3], 0.9 * 1280)
		self.assertLess(front[3], closing[3])
		self.assertEqual(
			front, layout(canvas, [("product", 1076, 717)], front=True)[0]
		)  # same inputs, same place

	def test_a_drawn_scene_keeps_the_floor_clear_for_the_pack_and_the_closing_scene_its_centre(self):
		from joymedia.services.planning.prompts import _product_note

		project = {"shots": [{"shot_number": 1}, {"shot_number": 2}]}
		refs = [
			{"reference_role": "Product", "asset_version": "AV1"},
			{"reference_role": "Character", "asset_version": "AV2"},
		]
		with patch.object(subject_overlay, "_cutout_path", return_value="/p.png"):
			story = _product_note(
				frappe._dict(shot_number=1, references=refs, character_mode="Draw in scene"), project
			)
			closing = _product_note(
				frappe._dict(shot_number=2, references=refs, character_mode="Draw in scene"), project
			)
		with patch.object(subject_overlay, "_cutout_path", return_value=None):
			no_cutout = _product_note(
				frappe._dict(shot_number=1, references=refs, character_mode="Draw in scene"), project
			)
		self.assertIn("unobstructed area", story)
		self.assertIn("do not draw a substitute product", story)
		self.assertIn("central area clear", closing)
		self.assertEqual("", no_cutout)


class TestProductLock(FrappeTestCase):
	def _assets(self, folder):
		from PIL import Image

		background, pack = folder / "bg.png", folder / "pack.png"
		Image.new("RGB", (360, 640), (40, 40, 40)).save(background)
		Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(pack)
		return background, pack

	def test_authored_surface_placement_overrides_default_floor_without_changing_art(self):
		from joymedia.services.keyframes.overlay import composite_subjects

		with tempfile.TemporaryDirectory() as folder:
			path = Path(folder) / "source.png"
			picture = Image.new("RGBA", (100, 50), (10, 50, 200, 255))
			picture.putpixel((0, 0), (0, 0, 0, 0))
			picture.save(path)
			background = io.BytesIO()
			Image.new("RGB", (400, 400), "white").save(background, "PNG")
			lock = {}
			result = composite_subjects(
				background.getvalue(),
				[{"role": "product", "path": str(path), "asset_version": "SOURCE"}],
				shadows=False,
				lock=lock,
				placements=[{"asset_version": "SOURCE", "box": [0.1, 0.2, 0.5, 0.25]}],
			)
			self.assertEqual([40, 80, 200, 100], list(lock["items"][0]["box"]))
			self.assertEqual((10, 50, 200), Image.open(io.BytesIO(result)).getpixel((100, 120)))
			with self.assertRaises(ValueError):
				composite_subjects(
					background.getvalue(),
					[],
					placements=[{"asset_version": "UNSELECTED", "box": [0.1, 0.2, 0.5, 0.25]}],
				)

	def test_the_paste_records_the_exact_pack_pixels_and_place(self):
		import tempfile
		from pathlib import Path

		with tempfile.TemporaryDirectory() as folder:
			background, pack = self._assets(Path(folder))
			lock = {}
			composite_subjects(
				background.read_bytes(), [{"role": "product", "path": str(pack)}], front=True, lock=lock
			)
		self.assertEqual([360, 640], lock["canvas"])
		self.assertEqual(1, len(lock["items"]))
		x, _y, width, _height = lock["items"][0]["box"]
		self.assertAlmostEqual(180, x + width / 2, delta=2)
		self.assertTrue(lock["items"][0]["png"].startswith(b"\x89PNG"))

	def _lock(self, folder, source):
		import subprocess

		from PIL import Image

		from joymedia.services.keyframes.overlay import lock_products_in_video

		video, locked, patch_file = folder / "in.mp4", folder / "out.mp4", folder / "patch.png"
		# The video is twice the keyframe's size: the box scales with it.
		subprocess.run(
			[
				"ffmpeg",
				"-v",
				"error",
				"-y",
				"-f",
				"lavfi",
				"-i",
				source,
				"-t",
				"2",
				"-pix_fmt",
				"yuv420p",
				str(video),
			],
			check=True,
		)
		Image.new("RGBA", (50, 40), (255, 0, 0, 255)).save(patch_file)
		lock = {
			"canvas": [360, 640],
			"items": [{"box": [100, 500, 50, 40], "file": "/private/files/patch.png"}],
		}
		with patch.object(
			subject_overlay.frappe,
			"get_doc",
			return_value=frappe._dict(get_full_path=lambda: str(patch_file)),
		):
			return lock_products_in_video(video, lock, locked, 24), locked

	def _pixel(self, folder, video, second):
		import subprocess

		from PIL import Image

		frame = folder / f"f{second}.png"
		subprocess.run(
			["ffmpeg", "-v", "error", "-y", "-ss", second, "-i", str(video), "-frames:v", "1", str(frame)],
			check=True,
		)
		with Image.open(frame) as image:
			return image.convert("RGB").getpixel((200 + 50, 1000 + 40))

	def test_the_exact_pack_is_laid_over_every_frame_while_it_stays_in_place(self):
		import tempfile
		from pathlib import Path

		with tempfile.TemporaryDirectory() as folder:
			folder = Path(folder)
			result, locked = self._lock(folder, "color=c=gray:s=720x1280:r=24")
			self.assertIsNotNone(result)
			for second in ("0.1", "1.9"):
				red = self._pixel(folder, locked, second)
				self.assertGreater(red[0], 200, second)
				self.assertLess(red[1] + red[2], 80, second)

	def test_a_video_whose_pack_region_changes_is_rejected_instead_of_silently_unprotected(self):
		import tempfile
		from pathlib import Path

		with tempfile.TemporaryDirectory() as folder:
			# The shot cuts to something else after 0.15 s, before the pack has stayed a quarter second.
			with self.assertRaisesRegex(ValueError, "lost coverage"):
				self._lock(
					Path(folder), "nullsrc=s=720x1280:r=24,geq=lum='if(lt(T,0.15),128,235)':cb=128:cr=128"
				)
			self.assertFalse((Path(folder) / "out.mp4").exists())

	def test_only_the_frames_that_still_show_the_pack_are_kept(self):
		from joymedia.services.keyframes.overlay import pack_still_frames

		same, other = bytes([100]) * 1024, bytes([200]) * 1024
		frames = [same] * 20 + [other] * 2 + [same] * 10 + [other] * 30 + [same] * 3
		# Even a two-frame paw crossing must not be painted over. The final short run stays excluded.
		self.assertEqual([(0, 19), (22, 31)], pack_still_frames(frames, tolerance=18))
		self.assertEqual([], pack_still_frames([]))


class TestEndCard(FrappeTestCase):
	def test_closing_motion_is_not_replaced_by_a_whole_shot_source_card(self):
		from joymedia.services.project.context import _compose_end_card

		shots = [
			{
				"shot_number": 1,
				"character_mode": "Draw in scene",
				"references": [{"reference_role": "Product"}],
			},
			{
				"shot_number": 2,
				"duration_seconds": 5,
				"character_mode": "Draw in scene",
				"references": [{"reference_role": "Product"}, {"reference_role": "Character"}],
			},
		]
		_compose_end_card(shots)
		self.assertEqual(["Draw in scene", "Draw in scene"], [row["character_mode"] for row in shots])
		self.assertNotIn("closing_hold_seconds", shots[-1])
		self.assertNotIn("closing_hold_mode", shots[-1])

	def test_a_last_scene_without_a_product_keeps_its_mode(self):
		from joymedia.services.project.context import _compose_end_card

		shots = [
			{
				"shot_number": 1,
				"character_mode": "Draw in scene",
				"references": [{"reference_role": "Character"}],
			}
		]
		_compose_end_card(shots)
		self.assertEqual("Draw in scene", shots[0]["character_mode"])


class TestSplitScreenKeyframe(FrappeTestCase):
	def test_each_view_is_a_panel_with_the_pack_in_its_middle_and_every_pack_is_locked(self):
		import io
		import tempfile

		from PIL import Image

		from joymedia.services.keyframes.overlay import split_screen_keyframe

		drawn = io.BytesIO()
		Image.new("RGB", (720, 1280), (90, 120, 90)).save(drawn, "PNG")
		with tempfile.NamedTemporaryFile(suffix=".png") as pack:
			cutout = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
			cutout.paste((20, 200, 180, 255), (20, 20, 180, 280))
			cutout.save(pack.name)
			lock = {}
			frame = split_screen_keyframe(
				drawn.getvalue(),
				[{"text": "A"}, {"text": "B"}, {"text": "C"}],
				"A room.",
				None,
				[{"role": "product", "path": pack.name, "asset_version": "AV-PACK"}],
				lock,
			)
		image = Image.open(io.BytesIO(frame)).convert("RGB")
		self.assertEqual((720, 1280), image.size)
		self.assertEqual([720, 1280], lock["canvas"])
		self.assertEqual(3, len(lock["items"]))
		tops = [item["box"][1] for item in lock["items"]]
		band = (1280 - 8 * 2) // 3
		for number, top in enumerate(tops):
			self.assertTrue(
				number * band <= top < (number + 1) * (band + 8), tops
			)  # each pack inside its own panel
		self.assertEqual((255, 255, 255), image.getpixel((360, band + 3)))  # the line between panels 1 and 2


class TestHeldProduct(FrappeTestCase):
	def _shot(self, action):
		return frappe._dict(
			generation_prompt=f"{action} Camera: Wide shot.\n\nAudio: a pop.",
			views_json="",
			character_mode="Draw in scene",
			references=[
				{"reference_role": "Character", "asset_version": "AV-ME"},
				{"reference_role": "Product", "asset_version": "AV-PACK"},
			],
		)

	def test_a_scene_whose_character_holds_the_product_is_recognised(self):
		from joymedia.services.planning.prompts import holds_product

		with patch("joymedia.services.keyframes.overlay._cutout_path", return_value="/tmp/x.png"):
			self.assertTrue(
				holds_product(
					self._shot(
						"The mother mascot beams and cradles in arms a giant jumbo bag of Shera soft pack."
					)
				)
			)
			self.assertTrue(holds_product(self._shot("The mother holds the product up to the camera.")))
			self.assertFalse(
				holds_product(self._shot("The kid spills juice. Later she holds the pack."))
			)  # not the opening action
			self.assertFalse(holds_product(self._shot("The mother smiles beside the table.")))

	def test_the_real_pack_covers_the_pack_the_character_was_drawn_holding(self):
		import io
		import tempfile

		from PIL import Image

		from joymedia.services.keyframes.overlay import paste_held_product

		drawn = io.BytesIO()
		Image.new("RGB", (720, 1280), (200, 200, 200)).save(drawn, "PNG")
		with tempfile.NamedTemporaryFile(suffix=".png") as pack:
			Image.new("RGBA", (300, 200), (20, 200, 180, 255)).save(pack.name)
			lock = {}
			with patch("joymedia.services.review.consistency.locate", return_value=(200, 600, 500, 800)):
				frame = paste_held_product(drawn.getvalue(), [{"role": "product", "path": pack.name}], lock)
			with patch("joymedia.services.review.consistency.locate", return_value=None):
				self.assertIsNone(
					paste_held_product(drawn.getvalue(), [{"role": "product", "path": pack.name}])
				)
		image = Image.open(io.BytesIO(frame)).convert("RGB")
		self.assertEqual((20, 200, 180), image.getpixel((350, 700)))
		self.assertEqual([[200, 600, 300, 200]], [item["box"] for item in lock["items"]])


class TestSharedStudioGround(unittest.TestCase):
	def test_product_hero_uses_the_primary_cell_without_distorting_artwork(self):
		from joymedia.services.keyframes.overlay import hero_layout

		for canvas in [(720, 1280), (1280, 720), (720, 720)]:
			sizes = [("character", 1000, 1000), ("product", 1500, 900)]
			boxes = hero_layout(canvas, sizes)
			actor, product = boxes
			self.assertGreater(product[2] * product[3], actor[2] * actor[3])
			self.assertTrue(actor[0] + actor[2] <= product[0] or actor[1] + actor[3] <= product[1])
			for (_, w, h), (x, y, bw, bh) in zip(sizes, boxes, strict=False):
				self.assertLess(abs(bw / bh - w / h), 0.01)
				self.assertTrue(0 <= x and 0 <= y and x + bw <= canvas[0] and y + bh <= canvas[1])

	def test_all_subjects_keep_proportions_and_one_baseline_without_overlap(self):
		from joymedia.services.keyframes.overlay import shared_ground_layout

		for canvas in [(720, 1280), (1280, 720), (512, 512)]:
			sizes = [("character", 400, 600, 1), ("product", 600, 400, 0.65)]
			boxes = shared_ground_layout(canvas, sizes)
			self.assertEqual(boxes[0][1] + boxes[0][3], boxes[1][1] + boxes[1][3])
			self.assertLessEqual(boxes[0][0] + boxes[0][2], boxes[1][0])
			for (_, w, h, _), (x, y, bw, bh) in zip(sizes, boxes, strict=False):
				self.assertLess(abs(bw / bh - w / h), 0.01)
				self.assertGreaterEqual(min(x, y), 0)
				self.assertLessEqual(x + bw, canvas[0])
				self.assertLessEqual(y + bh, canvas[1])


class TestProductOnlyStaging(FrappeTestCase):
	def test_a_product_only_staged_closing_uses_source_preparation_not_photo_cells(self):
		from unittest.mock import Mock

		from joymedia.services.keyframes.overlay import paste_subjects_into_keyframe

		shot = {
			"shot": "S",
			"shot_number": 1,
			"character_mode": "Draw in scene",
			"references": [
				{
					"reference_role": "Product",
					"asset_version": "PRODUCT",
					"preservation_mode": "source_pixels",
				}
			],
			"reference_retention": {"recipe_sha256": "frozen recipe"},
		}
		snapshot = {"shots": [shot]}
		with (
			patch(
				"joymedia.services.keyframes.overlay.frappe.db.get_value",
				side_effect=[frappe._dict(generation_task="TASK"), ("S", "RUN"), json.dumps(snapshot)],
			),
			patch(
				"joymedia.services.consistency.retention.retain", return_value=b"prepared source"
			) as retain,
			patch("joymedia.services.keyframes.overlay.closing_subjects") as cells,
		):
			result = paste_subjects_into_keyframe(Mock(name="ATTEMPT"), b"rendered staging")
		self.assertEqual(result, b"prepared source")
		retain.assert_called_once()
		cells.assert_not_called()

	def test_explicit_exact_art_mode_is_preserved_with_or_without_an_actor(self):
		from joymedia.services.keyframes.overlay import scene_mode

		for refs in ([], [{"reference_role": "Product"}], [{"reference_role": "Character"}]):
			self.assertEqual(scene_mode(refs, "Paste exact art"), "Paste exact art")
			self.assertEqual(scene_mode(refs, "Draw in scene"), "Draw in scene")
