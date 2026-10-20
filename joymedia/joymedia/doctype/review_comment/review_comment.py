import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import strip_html_tags

MAX_COMMENT_LENGTH = 2000


class ReviewComment(Document):
	"""A reviewer's note on one frame, or a range of frames, of a scene's take."""

	def validate(self):
		self.comment = " ".join(strip_html_tags(str(self.comment or "")).split())
		if not self.comment:
			frappe.throw(_("Write what should change."))
		if len(self.comment) > MAX_COMMENT_LENGTH:
			frappe.throw(_("A comment can have at most {0} characters.").format(MAX_COMMENT_LENGTH))
		if self.scope == "Scene":
			self.start_frame = self.end_frame = None
		elif self.start_frame is None or self.end_frame is None or int(self.start_frame) < 0 or int(self.end_frame) < int(self.start_frame):
			frappe.throw(_("The frame range must start at 0 or later and end at or after its start."))
		if frappe.db.get_value("Shot", self.shot, "media_project") != self.media_project:
			frappe.throw(_("The scene does not belong to this project."))
