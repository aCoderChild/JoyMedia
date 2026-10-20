import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, strip_html_tags


class VideoReviewFeedback(Document):
	def validate(self):
		from joymedia.services.review.feedback import CATEGORIES, STATUSES, _frame, annotation, target

		self.feedback = strip_html_tags(str(self.feedback or "")).strip()
		if not self.feedback or len(self.feedback) > 4000:
			frappe.throw(_("Write feedback of 1 to 4000 characters."))
		if (
			self.category not in CATEGORIES
			or self.priority not in ("Normal", "High")
			or self.status not in STATUSES
		):
			frappe.throw(_("Invalid review classification."))
		self.admin_response = strip_html_tags(str(self.admin_response or "")).strip()
		if len(self.admin_response) > 4000:
			frappe.throw(_("Administrator response is too long."))
		before = self.get_doc_before_save()
		if before:
			for key in (
				"media_project",
				"source_edit",
				"asset_version",
				"shot",
				"scope",
				"start_frame",
				"end_frame",
				"fps",
				"feedback",
				"annotation_json",
				"submission_key",
				"owner",
			):
				if self.get(key) != before.get(key):
					frappe.throw(_("The original review evidence cannot be changed."))
		else:
			root, asset, _version, shot, fps, limit = target(self.media_project, self.asset_version)
			if (
				root.name != self.media_project
				or asset.media_project != self.source_edit
				or shot != (self.shot or None)
			):
				frappe.throw(_("Review evidence does not match its video."))
			self.fps = fps
			if self.scope == "Video":
				self.start_frame = self.end_frame = None
			elif (
				self.scope not in ("Frame", "Range")
				or self.start_frame is None
				or self.end_frame is None
				or not 0 <= self.start_frame <= self.end_frame < limit
			):
				frappe.throw(_("Choose frames inside this version."))
			if self.scope != "Video":
				self.start_frame, self.end_frame = _frame(self.start_frame), _frame(self.end_frame)
				if self.scope == "Frame" and self.start_frame != self.end_frame:
					frappe.throw(_("A frame report must identify a single frame."))
			box = annotation(self.annotation_json)
			if box and self.scope == "Video":
				frappe.throw(_("A marked area must refer to a frame."))
			self.annotation_json = json.dumps(box) if box else None
		self.start_seconds = self.start_frame / self.fps if self.start_frame is not None else None
		if self.status in ("Resolved", "Dismissed"):
			if not before or before.status != self.status:
				self.resolved_by, self.resolved_at = frappe.session.user, now_datetime()
		else:
			self.resolved_by = self.resolved_at = None
