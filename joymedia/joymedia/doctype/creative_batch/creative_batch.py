import frappe
from frappe.model.document import Document


class CreativeBatch(Document):
	"""Durable product-reference automation state; media remains in native projects."""

	def validate(self):
		before = self.get_doc_before_save()
		if before and any(
			self.get(key) != before.get(key) for key in ("request_json", "source_project", "requested_by")
		):
			frappe.throw("A creative batch's frozen request cannot be changed. Create another batch.")
