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


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_audio_asset_versions(doctype, txt, searchfield, start, page_len, filters):
	"""Return Asset Versions whose parent Media Asset is audio."""
	asset_version = frappe.qb.DocType("Asset Version")
	media_asset = frappe.qb.DocType("Media Asset")
	return (
		frappe.qb.from_(asset_version)
		.inner_join(media_asset)
		.on(asset_version.media_asset == media_asset.name)
		.select(asset_version.name)
		.where(media_asset.media_type == "Audio")
		.where(asset_version.name.like(f"%{txt}%"))
		.orderby(asset_version.name)
		.limit(page_len)
		.offset(start)
		.run(as_list=True)
	)
