# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

import base64

import frappe
from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestAssetVersion(IntegrationTestCase):
	def test_duplicate_uploads_respect_asset_category(self):
		from joymedia.services.media_asset_service import create_media_asset
		image_bytes = base64.b64decode(
			"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
		)

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
