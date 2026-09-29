# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MediaAsset(Document):
	def validate(self):
		self.asset_name = (self.asset_name or "").strip()
		if not self.asset_name:
			frappe.throw(_("Asset Name is required."))
