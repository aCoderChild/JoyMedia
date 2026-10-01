# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


class ProjectReference(Document):
	def validate(self):
		project = frappe.get_doc("Media Project", self.parent) if self.parent else None
		if not self.reference_key:
			base = self.label or self.asset_version or "reference"
			self.reference_key = re.sub(r"[^a-z0-9]+", "_", str(base).lower()).strip("_") or "reference"
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
