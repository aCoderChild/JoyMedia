# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestMediaAsset(IntegrationTestCase):
	"""
	Integration tests for MediaAsset.
	Use this class for testing interactions between multiple components.
	"""

	def _asset(self, scope="Library"):
		asset = frappe.get_doc({
			"doctype": "Media Asset", "asset_name": "3", "media_type": "Image",
			"asset_category": "Reference", "asset_scope": "Library", "status": "Active",
		}).insert(ignore_permissions=True)
		asset.db_set("asset_scope", scope)
		return asset

	def test_library_asset_can_be_renamed_and_recategorised(self):
		from joymedia.services.media_asset_service import update_media_asset

		asset = self._asset()
		result = update_media_asset(asset.name, asset_name="  Hồ bơi  ", asset_category="Background")

		self.assertEqual({"media_asset": asset.name, "asset_name": "Hồ bơi", "asset_category": "Background"}, result)
		asset.reload()
		self.assertEqual(("Hồ bơi", "Background"), (asset.asset_name, asset.asset_category))

	def test_invalid_edits_are_rejected(self):
		from joymedia.services.media_asset_service import update_media_asset

		asset = self._asset()
		self.assertRaises(frappe.ValidationError, update_media_asset, asset.name, asset_name="   ")
		self.assertRaises(frappe.ValidationError, update_media_asset, asset.name, asset_category="Derived Audio")
		self.assertRaises(frappe.ValidationError, update_media_asset, self._asset("Project Output").name, asset_name="x")
