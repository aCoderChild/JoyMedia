# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AudioCue(Document):
	def validate(self):
		if (self.start_seconds or 0) < 0:
			frappe.throw(_("Audio Cue Start Seconds cannot be negative."))
		has_end_seconds = self.end_seconds is not None and self.end_seconds != ""
		if has_end_seconds and self.end_seconds <= self.start_seconds:
			frappe.throw(_("Audio Cue End Seconds must be greater than Start Seconds."))
		if (self.fade_in_seconds or 0) < 0 or (self.fade_out_seconds or 0) < 0:
			frappe.throw(_("Audio Cue fade durations cannot be negative."))
		if has_end_seconds and (self.fade_in_seconds or 0) + (self.fade_out_seconds or 0) > (
			self.end_seconds - self.start_seconds
		):
			frappe.throw(_("Audio Cue fades cannot exceed the cue duration."))
