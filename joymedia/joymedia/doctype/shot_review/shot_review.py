import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ShotReview(Document):
	def before_insert(self):
		if not self.reviewer:
			self.reviewer = frappe.session.user
		if not self.reviewed_at:
			self.reviewed_at = now_datetime()
