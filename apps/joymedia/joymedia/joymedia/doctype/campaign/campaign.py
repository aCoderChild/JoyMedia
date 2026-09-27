# Copyright (c) 2026, JoyMedia and Contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Campaign(Document):
	def validate(self):
		self.campaign_name = (self.campaign_name or "").strip()
		self.product_name = (self.product_name or "").strip()
		self.target_audience = (self.target_audience or "").strip()

		if not self.campaign_name:
			frappe.throw(_("Campaign Name is required."))
		if not self.client_organization:
			frappe.throw(_("Business is required."))
		if not self.product_name:
			frappe.throw(_("Product Name is required."))
		if not self.target_audience:
			frappe.throw(_("Target Audience is required."))
