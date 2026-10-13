import io
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import project_intake
from joymedia.services.e2e_setup import _generate_image_bytes


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
		with patch("joymedia.services.media_asset_service.create_media_asset", side_effect=frappe.ValidationError("boom")):
			with self.assertRaises(frappe.ValidationError):
				project_intake.create_project_from_brief(
					"Will fail", workbook_file=file_doc.name, references=[{"file_name": file_doc.name, "label": "x"}]
				)
		self.assertEqual(before, frappe.db.count("Media Project"))

	def test_duplicate_detection_never_returns_another_users_asset(self):
		from joymedia.services.media_asset_service import _get_duplicate_version

		with patch("joymedia.services.media_asset_service.frappe.db.sql", return_value=[]) as sql:
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
