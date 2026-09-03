# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

from PIL import Image

import frappe
from frappe.model.document import Document


class AssetVersion(Document):
	def validate(self):
		self.set_file_metadata()

	def before_insert(self):
		latest_version = frappe.db.get_value(
			"Asset Version",
			{"media_asset": self.media_asset},
			"max(version_number)",
		)
		self.version_number = (latest_version or 0) + 1

	def set_file_metadata(self):
		self.width = None
		self.height = None

		if not self.file:
			return

		media_asset = frappe.get_doc("Media Asset", self.media_asset)
		if media_asset.media_type == "Image":
			self.set_image_metadata()

	def set_image_metadata(self):
		file_doc = frappe.get_doc("File", {"file_url": self.file})
		with Image.open(file_doc.get_full_path()) as image:
			self.width, self.height = image.size
