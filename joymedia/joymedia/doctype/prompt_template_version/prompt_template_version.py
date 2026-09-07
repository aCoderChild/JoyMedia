# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document


IMMUTABLE_STATUSES = ("Production", "Deprecated")
IMMUTABLE_FIELDS = (
	"prompt_template",
	"version_number",
	"version_label",
	"template_body",
	"compilation_instructions",
	"change_notes",
)


class PromptTemplateVersion(Document):
	def validate(self):
		self._validate_immutable_content()
		self.template_hash = hashlib.sha256((self.template_body or "").encode("utf-8")).hexdigest()

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
			_("Prompt Template Version {0} is immutable after it is {1}.").format(self.name, previous.status)
		)
