# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document

from joymedia.workflow_adapters import get_workflow_adapter
from joymedia.workflow_adapters.base import canonical_workflow_json


IMMUTABLE_STATUSES = ("Production", "Deprecated")
IMMUTABLE_FIELDS = (
	"workflow_profile",
	"version_number",
	"version_label",
	"workflow_json",
	"model_cache_key",
	"change_notes",
	"bindings",
	"frame_count",
	"output_fps",
	"produces_video",
	"produces_audio",
)


class WorkflowVersion(Document):
	def validate(self):
		self._validate_immutable_content()
		workflow_data = frappe.parse_json(self.workflow_json)
		if not isinstance(workflow_data, dict):
			frappe.throw(_("Workflow JSON must define a JSON object."))
		self.workflow_hash = hashlib.sha256(canonical_workflow_json(workflow_data).encode("utf-8")).hexdigest()

		profile = frappe.get_doc("Workflow Profile", self.workflow_profile)
		for fieldname, value in get_workflow_adapter(profile).extract_execution_metadata(workflow_data).items():
			setattr(self, fieldname, value)

	def _validate_immutable_content(self):
		previous = self.get_doc_before_save()
		if not previous or previous.status not in IMMUTABLE_STATUSES:
			return

		changed_fields = [fieldname for fieldname in IMMUTABLE_FIELDS if self.has_value_changed(fieldname)]
		if not changed_fields and self.status == previous.status:
			return
		if previous.status == "Production" and self.status == "Deprecated" and not changed_fields:
			return
		frappe.throw(
			_("Workflow Version {0} is immutable after it is {1}.").format(self.name, previous.status)
		)
