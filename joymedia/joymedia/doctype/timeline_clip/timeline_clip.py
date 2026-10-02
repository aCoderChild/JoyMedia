import frappe
from frappe import _
from frappe.model.document import Document


class TimelineClip(Document):
	def validate(self):
		self.source_in_frame = int(self.source_in_frame or 0)
		self.source_out_frame = int(self.source_out_frame or 0)
		self.clip_order = int(self.clip_order or 0)
		self.track_index = int(self.track_index or 0)
		self.timeline_start_frame = int(self.timeline_start_frame or 0)
		self.transition_frames = int(self.transition_frames or 0)

		if self.clip_order < 1:
			frappe.throw(_("Timeline clip order must be at least 1."))
		if self.track_type not in ("Video", "Audio"):
			frappe.throw(_("Timeline clip track type must be Video or Audio."))
		if self.track_index < 0 or self.timeline_start_frame < 0:
			frappe.throw(_("Timeline clip track index and start frame cannot be negative."))
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
		if self.track_type == "Video" and self.audio_role:
			self.audio_role = None
		if self.track_type == "Audio" and not self.audio_role:
			self.audio_role = "SFX"
		if self.track_type == "Video" and self.linked_video_clip:
			self.linked_video_clip = None
