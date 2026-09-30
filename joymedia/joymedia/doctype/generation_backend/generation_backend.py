import frappe
from frappe.model.document import Document


class GenerationBackend(Document):
	def validate(self):
		if self.enabled and not self.endpoint_url:
			frappe.throw(frappe._("Enabled Generation Backends require an endpoint URL."))
