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
		row.reference_key
		for row in project.selected_media or []
		if row.name != reference.name and row.reference_key
	}
	counter = 2
	while key in used_keys:
		suffix = f"_{counter}"
		key = f"{base[: 100 - len(suffix)]}{suffix}"
		counter += 1
	reference.reference_key = key


def assign_identity_key(reference):
	"""Make a single uploaded reference its own identity by default.

	A user may deliberately put several views under one identity key.  Keeping
	the default equal to the unique reference key is fully backward compatible.
	"""
	if not reference.identity_key:
		reference.identity_key = reference.reference_key


def assign_reference_role(reference):
	"""Classify a reference added without a role from its name.

	Uploads, API calls and the desk form all go through the parent's validate, so clients are never
	asked to know the role vocabulary. An explicit role is always kept.
	"""
	if not reference.reference_role and (reference.label or reference.reference_key):
		from joymedia.services.intake.project import infer_reference_role

		reference.reference_role = infer_reference_role(reference.label or reference.reference_key)


def assign_relative_size(reference):
	"""Give a newly added child character about half its parent's height, read from its name.

	The image model cannot work out that "Gấu con" is a cub beside "Gấu mẹ": without a size both are drawn alike.
	Only a new Character or Person row still at the default 1 is changed, so a size someone set is always kept.
	"""
	if reference.reference_role not in ("Character", "Person") or not (
		reference.get("__islocal") or reference.is_new()
	):
		return
	if float(reference.relative_size or 1) != 1:
		return
	from joymedia.services.intake.project import infer_relative_size

	reference.relative_size = infer_relative_size(reference.label or reference.reference_key or "")


class ProjectReference(Document):
	def validate(self):
		assign_reference_role(self)
		project = frappe.get_doc("Media Project", self.parent) if self.parent else None
		if project:
			assign_reference_key(self, project)
		assign_identity_key(self)
		self.reference_key = self.reference_key[:100]
		self.identity_key = self.identity_key[:100]
		if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", self.reference_key):
			frappe.throw(_("Reference Key must contain only lowercase letters, numbers, and underscores."))
		if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", self.identity_key):
			frappe.throw(_("Identity Key must contain only lowercase letters, numbers, and underscores."))
		if project:
			duplicates = [
				row.name
				for row in project.selected_media or []
				if row.name != self.name and row.reference_key == self.reference_key
			]
			if duplicates:
				frappe.throw(
					_("Reference Key '{0}' must be unique within the Media Project.").format(
						self.reference_key
					)
				)
			identity_roles = {
				row.reference_role
				for row in project.selected_media or []
				if row.name != self.name and row.identity_key == self.identity_key and row.reference_role
			}
			if identity_roles and self.reference_role not in identity_roles:
				frappe.throw(
					_("All views of Identity Key '{0}' must use the same Reference Role.").format(
						self.identity_key
					)
				)
			active = frappe.db.exists(
				"Generation Run",
				{"media_project": project.name, "status": ["in", ["Queued", "Running"]]},
			)
			if active and any(
				self.has_value_changed(fieldname)
				for fieldname in (
					"reference_key",
					"identity_key",
					"reference_role",
					"product_view",
					"label",
					"asset_version",
				)
			):
				frappe.throw(_("Project References cannot change while generation is active."))
