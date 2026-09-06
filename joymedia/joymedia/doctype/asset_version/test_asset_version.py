# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestAssetVersion(IntegrationTestCase):
	def test_versions_are_numbered_per_media_asset(self):
		organization = frappe.get_doc(
			{
				"doctype": "Client Organization",
				"organization_name": "Asset Version Numbering Test",
			}
		).insert()
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": "Asset Version Numbering Test",
				"asset_scope": "Organization",
				"client_organization": organization.name,
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
