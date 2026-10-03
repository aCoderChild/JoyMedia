# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import re
import unicodedata

import frappe
from frappe import _
from frappe.model.document import Document


def assign_reference_key(reference, project):
	if reference.reference_key:
		return
	base = (reference.label or "").strip()
	if not base and reference.asset_version:
		media_asset = frappe.db.get_value("Asset Version", reference.asset_version, "media_asset")
		base = frappe.db.get_value("Media Asset", media_asset, "asset_name") if media_asset else ""
	base = base or reference.reference_role or "reference"
	# Transliterate accented names ("tòa tháp" -> "toa_thap") instead of dropping letters.
	base = unicodedata.normalize("NFKD", str(base).replace("đ", "d").replace("Đ", "D"))
	base = base.encode("ascii", "ignore").decode("ascii")
	base = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or "reference"
	key = base[:100]
	used_keys = {
		row.reference_key for row in project.selected_media or []
		if row.name != reference.name and row.reference_key
	}
	counter = 2
	while key in used_keys:
		suffix = f"_{counter}"
		key = f"{base[:100 - len(suffix)]}{suffix}"
		counter += 1
	reference.reference_key = key


class ProjectReference(Document):
	def validate(self):
		project = frappe.get_doc("Media Project", self.parent) if self.parent else None
		if project:
			assign_reference_key(self, project)
		self.reference_key = self.reference_key[:100]
		if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", self.reference_key):
			frappe.throw(_("Reference Key must contain only lowercase letters, numbers, and underscores."))
		if project:
			duplicates = [
				row.name for row in project.selected_media or []
				if row.name != self.name and row.reference_key == self.reference_key
			]
			if duplicates:
				frappe.throw(_("Reference Key '{0}' must be unique within the Media Project.").format(self.reference_key))
			active = frappe.db.exists(
				"Generation Run",
				{"media_project": project.name, "status": ["in", ["Queued", "Running"]]},
			)
			if active and any(
				self.has_value_changed(fieldname)
				for fieldname in ("reference_key", "reference_role", "label", "asset_version")
			):
				frappe.throw(_("Project References cannot change while generation is active."))
