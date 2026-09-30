import frappe
from frappe import _
from frappe.model.document import Document


class TimelineClip(Document):
	def validate(self):
		self.source_in_frame = int(self.source_in_frame or 0)
		self.source_out_frame = int(self.source_out_frame or 0)
		self.clip_order = int(self.clip_order or 0)
		self.transition_frames = int(self.transition_frames or 0)

		if self.clip_order < 1:
			frappe.throw(_("Timeline clip order must be at least 1."))
		if self.source_in_frame < 0:
			frappe.throw(_("Timeline clip source in frame cannot be negative."))
		if self.source_out_frame <= self.source_in_frame:
			frappe.throw(_("Timeline clip source out frame must be after the source in frame."))
		if self.transition_to_next not in ("Cut", "Dissolve", "Fade"):
			frappe.throw(_("Unsupported timeline transition."))
		if self.transition_frames < 0:
			frappe.throw(_("Transition frames cannot be negative."))
		if self.transition_to_next == "Cut":
			self.transition_frames = 0
