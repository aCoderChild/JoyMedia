# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ComfyuiWorker(Document):
	def validate(self):
		if (self.max_concurrent_jobs or 0) < 1:
			frappe.throw(_("Max Concurrent Jobs must be greater than zero."))
