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
			self.assertEqual((255, 0, 0), result.getpixel((x + width - 5, y + height - 5)))
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
		snapshot = {"shots": [{"shot": "S1", "references": [{"reference_role": "person", "asset_version": "AV1"}]}]}
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
		references = frappe._dict(references=[
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
