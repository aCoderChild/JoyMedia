import io
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.intake import project as project_intake
from joymedia.tests.support.e2e_setup import _generate_image_bytes


class TestInference(FrappeTestCase):
	def test_reference_roles_are_guessed_from_english_and_vietnamese_names(self):
		role = project_intake.infer_reference_role
		self.assertEqual("Character", role("Gau Shera mascot"))
		self.assertEqual("Character", role("Gấu mẹ"))
		self.assertEqual("Product", role("Shera pack"))
		self.assertEqual("Product", role("Hộp giấy"))
		self.assertEqual("Environment", role("Living room"))
		self.assertEqual("General", role("IMG_0042"))

	def test_format_follows_the_first_aspect_ratio_in_the_text(self):
		preset = project_intake.format_preset
		self.assertEqual("Portrait", preset(" 9:16 (Dọc cho TikTok) & 16:9 (TVC)"))
		self.assertEqual("Landscape", preset("16:9 widescreen"))
		self.assertEqual("Square", preset("1:1"))
		self.assertIsNone(preset("any size"))
		self.assertIsNone(preset(None))


def _workbook_bytes(format_text="9:16 (dọc)", duration="10s"):
	from openpyxl import Workbook

	wb = Workbook()
	ws = wb.active
	ws.title = "Demo 1"
	for row in (
		("Tên sản phẩm", "Khăn giấy Shera"), ("Mục tiêu", "Quảng cáo"), ("Thời lượng", duration), ("Định dạng", format_text),
		("Tone & Mood", "Dễ thương"), (),
		("Phân cảnh", "Thời lượng", "Hình ảnh & Góc máy", "Hành động", "Lời thoại", "Âm thanh", "Chữ hiển thị"),
		("Hook", "0:00 - 0:05", "Cận cảnh", "Gấu rút giấy", "", "", "x"),
		("Kết", "0:05 - 0:10", "Trung cảnh", "Gấu cười", "", "", "x"),
	):
		ws.append(row)
	buffer = io.BytesIO()
	wb.save(buffer)
	return buffer.getvalue()


class TestCreateFromBrief(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _file(self, name, content):
		return frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 1}).insert(ignore_permissions=True)

	def test_a_workbook_and_two_images_become_a_project_with_format_and_roles(self):
		workbook = self._file("story.xlsx", _workbook_bytes())
		mascot = self._file("mascot.png", _generate_image_bytes())
		pack = self._file("pack.png", _generate_image_bytes() + b"\x00")
		result = project_intake.create_project_from_brief(
			"Intake test", workbook_file=workbook.name,
			references=[{"file_name": mascot.name, "label": "Gau Shera mascot"}, {"file_name": pack.name, "label": "Shera pack", "role": ""}],
		)
		project = frappe.get_doc("Media Project", result["project"])

		self.assertEqual("Portrait", project.delivery_preset)
		self.assertEqual((720, 1280), (project.delivery_width, project.delivery_height))
		self.assertEqual(10, project.total_duration_seconds)
		self.assertEqual(2, frappe.db.count("Shot", {"media_project": project.name}))
		self.assertEqual({"Character", "Product"}, {row.reference_role for row in project.selected_media})
		self.assertEqual({"gau_shera_mascot", "shera_pack"}, {row.reference_key for row in project.selected_media})

	def test_readiness_lists_what_is_missing_in_order(self):
		result = project_intake.create_project_from_brief("Empty")
		steps = {step["key"]: step for step in result["readiness"]["steps"]}

		self.assertFalse(result["readiness"]["ready"])
		self.assertEqual("todo", steps["story"]["status"])
		self.assertEqual("todo", steps["approval"]["status"])
		self.assertEqual("story", result["readiness"]["next"])

	def test_a_bad_format_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			project_intake.create_project_from_brief("Bad format", format="sideways")


class TestIntakeIsAtomicAndPrivate(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_failure_after_the_import_leaves_no_half_built_project(self):
		file_doc = frappe.get_doc({"doctype": "File", "file_name": "w.xlsx", "content": _workbook_bytes(), "is_private": 1}).insert(ignore_permissions=True)
		before = frappe.db.count("Media Project")
		with patch("joymedia.services.intake.assets.create_media_asset", side_effect=frappe.ValidationError("boom")):
			with self.assertRaises(frappe.ValidationError):
				project_intake.create_project_from_brief(
					"Will fail", workbook_file=file_doc.name, references=[{"file_name": file_doc.name, "label": "x"}]
				)
		self.assertEqual(before, frappe.db.count("Media Project"))

	def test_duplicate_detection_never_returns_another_users_asset(self):
		from joymedia.services.intake.assets import _get_duplicate_version

		with patch("joymedia.services.intake.assets.frappe.db.sql", return_value=[]) as sql:
			_get_duplicate_version("hash", "AV", "Image", "Product")
		self.assertIn("ma.owner = %s", sql.call_args.args[0])
		self.assertEqual(frappe.session.user, sql.call_args.args[1][-1])


class TestNamingAndLanguage(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_project_without_a_name_is_named_from_its_workbook(self):
		frappe.set_user("Administrator")
		workbook = frappe.get_doc({"doctype": "File", "file_name": "n.xlsx", "content": _workbook_bytes(), "is_private": 1}).insert(ignore_permissions=True)
		with patch.object(frappe.db, "commit"):
			result = project_intake.create_project_from_brief(workbook_file=workbook.name)
		self.assertEqual("Khăn giấy Shera — Demo 1", frappe.db.get_value("Media Project", result["project"], "project_name"))

	def test_readiness_follows_the_requested_language(self):
		frappe.set_user("Administrator")
		with patch.object(frappe.db, "commit"):
			project = project_intake.create_project_from_brief("Lang test")["project"]
		vi = {s["key"]: s["label"] for s in project_intake.get_project_readiness(project, lang="vi")["steps"]}
		en = {s["key"]: s["label"] for s in project_intake.get_project_readiness(project, lang="en")["steps"]}
		self.assertEqual("Định dạng video", vi["format"])
		self.assertEqual("Video format", en["format"])


class TestWorkbookPreview(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_preview_reports_format_length_and_scenes_without_creating_anything(self):
		frappe.set_user("Administrator")
		workbook = frappe.get_doc({"doctype": "File", "file_name": "p.xlsx", "content": _workbook_bytes("16:9", "10s"), "is_private": 1}).insert(ignore_permissions=True)
		before = frappe.db.count("Media Project")
		demo = project_intake.preview_workbook(workbook.name)["demos"][0]

		self.assertEqual("Demo 1", demo["name"])
		self.assertEqual("Landscape", demo["format"])
		self.assertEqual(10, demo["duration_seconds"])
		self.assertEqual(2, demo["scene_count"])
		self.assertEqual(before, frappe.db.count("Media Project"))

	def test_a_non_workbook_is_refused(self):
		frappe.set_user("Administrator")
		image = frappe.get_doc({"doctype": "File", "file_name": "a.png", "content": _generate_image_bytes(), "is_private": 1}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			project_intake.preview_workbook(image.name)


class TestSchedulerTickWarning(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _steps(self, tick):
		frappe.set_user("Administrator")
		with patch.object(frappe.db, "commit"):
			project = project_intake.create_project_from_brief("Tick")["project"]
		with patch("frappe.utils.scheduler.get_scheduler_tick", return_value=tick):
			return {s["key"]: s for s in project_intake.get_project_readiness(project)["steps"]}

	def test_a_slow_scheduler_tick_is_reported_but_does_not_block_generation(self):
		step = self._steps(240)["scheduler"]
		self.assertEqual("note", step["status"])
		self.assertIn("240", step["detail"])

	def test_a_one_minute_tick_is_fine(self):
		self.assertEqual("done", self._steps(60)["scheduler"]["status"])


class TestPdfImages(FrappeTestCase):
	def test_pictures_are_extracted_with_alpha_and_page_text_and_small_ones_are_skipped(self):
		import tempfile
		from pathlib import Path

		from PIL import Image

		from joymedia.services.intake.project import extract_pdf_images

		with tempfile.TemporaryDirectory() as folder:
			path = Path(folder) / "catalogue.pdf"
			big = Image.new("RGB", (300, 400), (200, 30, 30))
			icon = Image.new("RGB", (40, 40), (0, 0, 0))
			big.save(path, "PDF", save_all=True, append_images=[big, icon])
			found = extract_pdf_images(path)
		# The same picture on two pages is reported once; the icon is skipped.
		self.assertEqual(1, len(found))
		self.assertEqual((300, 400), (found[0]["width"], found[0]["height"]))
		self.assertFalse(found[0]["has_alpha"])
		self.assertTrue(found[0]["png"].startswith(b"\x89PNG"))


class TestStudioSettings(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		from joymedia.api.projects import create_project

		self.project = create_project("Studio settings", "", "A film.")
		self.addCleanup(frappe.db.rollback)

	def test_the_three_modes_are_saved_validated_and_returned(self):
		from joymedia.api.projects import save_project_video_settings

		with patch.object(frappe.db, "commit"):
			saved = save_project_video_settings(
				self.project.name, 10, "Portrait", character_mode="Paste exact art", soundtrack_mode="Sound effects only",
				planning_mode="Follow the sheet",
			)
		self.assertEqual(("Paste exact art", "Sound effects only", "Follow the sheet"), (
			saved["character_mode"], saved["soundtrack_mode"], saved["planning_mode"]))
		with self.assertRaises(frappe.ValidationError), patch.object(frappe.db, "commit"):
			save_project_video_settings(self.project.name, 10, "Portrait", character_mode="Nonsense")

	def test_a_reference_size_is_validated_and_saved(self):
		from joymedia.api.assets import set_reference_size

		with self.assertRaises(frappe.ValidationError):
			set_reference_size(self.project.name, "AV-NONE", 0.5)
		with self.assertRaises(frappe.ValidationError):
			set_reference_size(self.project.name, "AV-NONE", 9)
