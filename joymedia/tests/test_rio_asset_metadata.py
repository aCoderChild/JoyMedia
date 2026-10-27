import io

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image


class TestRioAssetMetadata(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_studio_label_and_category_persist_on_project_reference(self):
		from joymedia.api.assets import (
			remove_project_asset,
			select_project_asset,
			update_project_reference_metadata,
		)
		from joymedia.api.projects import create_project
		from joymedia.services.intake.assets import create_media_asset
		from joymedia.services.project.context import _get_project_selected_assets

		buffer = io.BytesIO()
		Image.new("RGB", (32, 32), (220, 180, 120)).save(buffer, format="PNG")
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "rio-reference.png",
				"content": buffer.getvalue(),
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		asset = create_media_asset("Source image", "Product", file_name=file_doc.name)
		project_name = create_project("RIO metadata test", "Sample", "A simple sample video.").name
		frappe.db.set_value("Media Project", project_name, "total_duration_seconds", 3)
		select_project_asset(project_name, asset["media_asset"], "Product", "Source image")
		selected = _get_project_selected_assets(project_name)[0]
		shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": project_name,
				"shot_number": 1,
				"generation_prompt": "The product is on a table.",
				"duration_seconds": 3,
				"generation_inputs": [{"reference_role": "Product", "asset_version": selected.asset_version}],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Media Project", project_name, "storyboard_approval_status", "Approved")
		result = update_project_reference_metadata(
			project_name, selected.asset_version, label="Package front", reference_role="Environment"
		)
		self.assertEqual((result["label"], result["reference_role"]), ("Package front", "Environment"))
		fresh = _get_project_selected_assets(project_name)[0]
		self.assertEqual((fresh.label, fresh.reference_role), ("Package front", "Environment"))
		self.assertEqual(frappe.get_doc("Shot", shot.name).generation_inputs[0].reference_role, "Environment")
		self.assertEqual(
			frappe.db.get_value("Media Asset", asset["media_asset"], "asset_name"), "Source image"
		)
		self.assertEqual(
			frappe.db.get_value("Media Project", project_name, "storyboard_approval_status"),
			"Ready for Review",
		)
		with self.assertRaises(frappe.ValidationError):
			update_project_reference_metadata(project_name, selected.asset_version, label="")
		with self.assertRaises(frappe.ValidationError):
			update_project_reference_metadata(project_name, selected.asset_version, reference_role="Audio")
		frappe.db.set_value("Media Project", project_name, "storyboard_approval_status", "Approved")
		remove_project_asset(project_name, selected.asset_version)
		self.assertFalse(frappe.get_doc("Shot", shot.name).generation_inputs)
		self.assertEqual(
			frappe.db.get_value("Media Project", project_name, "storyboard_approval_status"),
			"Ready for Review",
		)
