import frappe
from frappe.model.document import Document


class AIModelProfile(Document):
	def validate(self):
		if self.enabled and not self.adapter_key:
			frappe.throw(frappe._("Enabled AI Model Profiles require an adapter key."))
