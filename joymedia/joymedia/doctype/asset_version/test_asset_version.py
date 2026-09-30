# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

from io import BytesIO

import frappe
from PIL import Image
from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestAssetVersion(IntegrationTestCase):
	def test_media_asset_category_contract(self):
		field = frappe.get_meta("Media Asset").get_field("asset_category")
		options = {option for option in (field.options or "").splitlines() if option}

		self.assertIn("Style", options)
		self.assertNotIn("Storyboard", options)
		self.assertIn("Other", options)
		self.assertNotIn("Shot Output", options)
		self.assertNotIn("Final Deliverable", options)
		scope = frappe.get_meta("Media Asset").get_field("asset_scope")
		self.assertEqual({"Library", "Project Output"}, set((scope.options or "").splitlines()))

	def test_duplicate_uploads_respect_asset_category(self):
		from joymedia.services.media_asset_service import create_media_asset
		image_buffer = BytesIO()
		color = tuple(int(frappe.generate_hash(length=6)[index : index + 2], 16) for index in (0, 2, 4))
		Image.new("RGB", (1, 1), color=color).save(image_buffer, format="PNG")
		image_bytes = image_buffer.getvalue()

		file_a = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "duplicate-category-a.png",
				"content": image_bytes,
				"is_private": 1,
				"owner": frappe.session.user,
			}
		).insert(ignore_permissions=True)
		first = create_media_asset("Duplicate Category A", "Brand", file_a.file_url)

		file_b = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "duplicate-category-b.png",
				"content": image_bytes,
				"is_private": 1,
				"owner": frappe.session.user,
			}
		).insert(ignore_permissions=True)
		same_category = create_media_asset("Duplicate Category B", "Brand", file_b.file_url)

		file_c = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "duplicate-category-c.png",
				"content": image_bytes,
				"is_private": 1,
				"owner": frappe.session.user,
			}
		).insert(ignore_permissions=True)
		different_category = create_media_asset("Duplicate Category C", "Reference", file_c.file_url)

		self.assertFalse(first["reused"])
		self.assertTrue(same_category["reused"])
		self.assertEqual(same_category["media_asset"], first["media_asset"])
		self.assertFalse(different_category["reused"])
		self.assertNotEqual(different_category["media_asset"], first["media_asset"])

	def test_versions_are_numbered_per_media_asset(self):
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": "Asset Version Numbering Test",
				"media_type": "Document",
				"asset_category": "Other",
			}
		).insert()
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "asset-version-numbering-test.txt",
				"content": b"asset version numbering smoke test",
				"is_private": 1,
				"attached_to_doctype": "Media Asset",
				"attached_to_name": asset.name,
			}
		).insert()

		first_version = frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": asset.name,
				"file": file_doc.file_url,
				"source": "Uploaded",
			}
		).insert()
		second_version = frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": asset.name,
				"file": file_doc.file_url,
				"source": "Uploaded",
			}
		).insert()

		self.assertEqual(first_version.version_number, 1)
		self.assertEqual(second_version.version_number, 2)
