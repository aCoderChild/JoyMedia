# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document


class GenerationRun(Document):
	IMMUTABLE_FIELDS = (
		"media_project",
		"workflow",
		"project_snapshot_json",
		"project_snapshot_hash",
		"execution_scope_json",
		"requested_by",
	)

	def validate(self):
		if not self.media_project or not frappe.db.exists("Media Project", self.media_project):
			frappe.throw(_("Generation Run requires an existing Media Project."))
		if self.is_new():
			project = frappe.get_doc("Media Project", self.media_project)
			if not self.workflow:
				self.workflow = project.workflow
		else:
			self._validate_immutable_fields()
		self._validate_snapshot()

	def _validate_immutable_fields(self):
		previous = frappe.db.get_value(
			"Generation Run", self.name, list(self.IMMUTABLE_FIELDS), as_dict=True
		)
		if not previous:
			return
		for fieldname in self.IMMUTABLE_FIELDS:
			current_value = self.get(fieldname) or None
			previous_value = previous.get(fieldname) or None
			if current_value != previous_value:
				frappe.throw(
					_("Generation Run {0} field {1} is immutable after creation.").format(
						self.name, fieldname
					)
				)

	def _validate_snapshot(self):
		if not self.project_snapshot_json or not self.project_snapshot_hash:
			frappe.throw(_("Generation Run requires a project snapshot and snapshot hash."))
		try:
			snapshot = frappe.parse_json(self.project_snapshot_json)
		except (TypeError, ValueError):
			frappe.throw(_("Generation Run {0} has invalid project snapshot JSON.").format(self.name or "new"))
		canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
		expected_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
		if self.project_snapshot_hash != expected_hash:
			frappe.throw(_("Generation Run {0} project snapshot hash does not match its snapshot.").format(self.name or "new"))
		if snapshot.get("media_project") != self.media_project:
			frappe.throw(_("Generation Run project snapshot belongs to another Media Project."))
		if snapshot.get("workflow") != self.workflow:
			frappe.throw(_("Generation Run project snapshot workflow does not match the Run workflow."))
		if self.execution_scope_json:
			try:
				scope = frappe.parse_json(self.execution_scope_json)
			except (TypeError, ValueError):
				frappe.throw(_("Generation Run {0} has invalid execution scope JSON.").format(self.name or "new"))
			if not isinstance(scope, dict):
				frappe.throw(_("Generation Run execution scope must be a JSON object."))
