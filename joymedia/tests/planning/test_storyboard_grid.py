import io
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.file_manager import save_file
from PIL import Image

from joymedia.services.planning.storyboard_grid import add_blank_scene, grid_boxes, import_grid, update_scene


class TestStoryboardGrid(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Grid toolbox test",
				"product_name": "Grid sample",
				"video_idea": "A supplied storyboard.",
				"total_duration_seconds": 5,
				"delivery_preset": "Landscape",
				"delivery_width": 1280,
				"delivery_height": 720,
			}
		).insert(ignore_permissions=True)
		buffer = io.BytesIO()
		Image.new("RGB", (101, 103), "red").save(buffer, format="PNG")
		self.source = save_file(
			"grid-test.png", buffer.getvalue(), "Media Project", self.project.name, is_private=1
		)

	def test_grid_includes_all_edge_pixels(self):
		boxes = grid_boxes(101, 103, 2, 2)
		self.assertEqual((50, 51, 101, 103), boxes[-1])
		self.assertEqual(101 * 103, sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in boxes))
		with self.assertRaises(ValueError):
			grid_boxes(2, 2, 3, 3)

	def test_blank_scene_preserves_existing_timing_and_starts_no_jobs(self):
		with patch.object(frappe, "enqueue") as queue:
			first = add_blank_scene(self.project.name, 3)["shot"]
			second = add_blank_scene(self.project.name, 7)["shot"]
		self.assertEqual(3, frappe.db.get_value("Shot", first, "duration_seconds"))
		self.assertEqual(7, frappe.db.get_value("Shot", second, "duration_seconds"))
		queue.assert_not_called()

	def test_every_panel_becomes_a_scene_and_retry_does_not_duplicate(self):
		with patch.object(frappe, "enqueue") as queue:
			result = import_grid(self.project.name, self.source.name, 2, 2, request_id="same-request")
			again = import_grid(self.project.name, self.source.name, 2, 2, request_id="same-request")
		self.assertEqual(result, again)
		self.assertEqual(4, frappe.db.count("Shot", {"media_project": self.project.name}))
		self.assertEqual(4, len(frappe.get_doc("Media Project", self.project.name).selected_media))
		for shot in result["shots"]:
			self.assertEqual("first_frame", frappe.get_doc("Shot", shot).generation_inputs[0].reference_role)
		queue.assert_not_called()

	def test_replacement_mismatch_and_busy_project_fail_before_writing(self):
		with self.assertRaises(frappe.ValidationError):
			import_grid(self.project.name, self.source.name, 2, 2, mode="existing", request_id="mismatch")
		self.assertEqual(0, frappe.db.count("Shot", {"media_project": self.project.name}))
		self.project.db_set("export_status", "Running", update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			add_blank_scene(self.project.name)

	def test_other_account_cannot_import_into_project(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				import_grid(self.project.name, self.source.name, request_id="forbidden")
		finally:
			frappe.set_user("Administrator")

	def test_scene_editor_saves_without_changing_other_scene_timing_or_starting_jobs(self):
		first = add_blank_scene(self.project.name, 3)["shot"]
		second = add_blank_scene(self.project.name, 7)["shot"]
		modified = str(frappe.db.get_value("Shot", first, "modified"))
		with patch.object(frappe, "enqueue") as queue:
			result = update_scene(self.project.name, first, "Opening", "A close-up of the supplied product.", 4, expected_modified=modified)
		self.assertEqual("Opening", frappe.db.get_value("Shot", first, "shot_name"))
		self.assertEqual(4, result["duration"])
		self.assertEqual(7, frappe.db.get_value("Shot", second, "duration_seconds"))
		self.assertEqual(11, frappe.db.get_value("Media Project", self.project.name, "total_duration_seconds"))
		queue.assert_not_called()
		with self.assertRaises(frappe.ValidationError):
			update_scene(self.project.name, first, "Stale title", "A different action.", 5, expected_modified=modified)
		self.assertEqual("Opening", frappe.db.get_value("Shot", first, "shot_name"))

	def test_scene_editor_rejects_invalid_timing_and_cross_project_scenes(self):
		name = add_blank_scene(self.project.name)["shot"]
		with self.assertRaises(frappe.ValidationError):
			update_scene(self.project.name, name, "Scene", "A product.", float("nan"))
		other = frappe.copy_doc(self.project).insert(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			update_scene(other.name, name, "Scene", "A product.", 5)

	def test_title_or_timing_edit_does_not_replace_existing_generation_directions(self):
		name = add_blank_scene(self.project.name)["shot"]
		frappe.db.set_value("Shot", name, {"generation_prompt": "Detailed camera and movement directions.", "storyboard_action": "A product on a table."})
		update_scene(self.project.name, name, "New title", "A product on a table.", 6, description_changed=False)
		self.assertEqual("Detailed camera and movement directions.", frappe.db.get_value("Shot", name, "generation_prompt"))
