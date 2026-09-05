# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document


# TODO: recheck the H3 model family defaults
H3_DEFAULTS = {
	"execution_width": 1344,
	"execution_height": 768,
	"output_fps": 24,
	"frame_count": 124,
	"produces_video": 1,
	"produces_audio": 1,
}


class WorkflowVersion(Document):
	def validate(self):
		self._validate_unique_version_number()
		workflow_data = self._parse_workflow_json()
		self._set_workflow_hash(workflow_data)
		self._extract_execution_characteristics(workflow_data)
		self._validate_bindings(workflow_data)

	def _validate_unique_version_number(self):
		if not self.workflow_profile or self.version_number is None:
			return

		filters = {"workflow_profile": self.workflow_profile, "version_number": self.version_number}
		if self.name:
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Workflow Version", filters):
			frappe.throw(_("Workflow Version Number must be unique within a Workflow Profile."))

	def _parse_workflow_json(self):
		if not self.workflow_json:
			frappe.throw(_("Workflow JSON is required."))

		try:
			return json.loads(self.workflow_json)
		except json.JSONDecodeError as exc:
			frappe.throw(_("Workflow JSON is invalid: {0}").format(str(exc)))

	def _set_workflow_hash(self, workflow):
		canonical = json.dumps(workflow, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
		self.workflow_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

	def _extract_execution_characteristics(self, workflow):
		conditioning_node = self._find_node_by_class(workflow, "MiniMaxH3ImageToVideo")
		if conditioning_node:
			inputs = conditioning_node.get("inputs", {})
			self.execution_width = inputs.get("width")
			self.execution_height = inputs.get("height")
			self.frame_count = inputs.get("length")

		save_node = self._find_node_by_class(workflow, "VHS_VideoCombine")
		if save_node:
			inputs = save_node.get("inputs", {})
			self.output_fps = inputs.get("frame_rate")
			self.produces_video = bool(inputs.get("images"))
			self.produces_audio = bool(inputs.get("audio"))

		profile = frappe.db.get_value(
			"Workflow Profile", self.workflow_profile, ["profile_name", "workflow_code"], as_dict=True
		)
		profile_identity = ""
		if profile:
			profile_identity = f"{profile.profile_name or ''} {profile.workflow_code or ''}".lower()

		for fieldname, default in H3_DEFAULTS.items():
			if getattr(self, fieldname, None) is None and "h3" in profile_identity:
				setattr(self, fieldname, default)

	def _find_node_by_class(self, workflow, class_type):
		for node in workflow.values():
			if node.get("class_type") == class_type:
				return node
		return None

	def _validate_bindings(self, workflow):
		seen_keys = set()
		for binding in self.bindings or []:
			if binding.binding_key in seen_keys:
				frappe.throw(_("Duplicate Workflow Binding key: {0}").format(binding.binding_key))
			seen_keys.add(binding.binding_key)

			node = workflow.get(binding.node_key)
			if node is None:
				frappe.throw(
					_("Workflow Binding '{0}' references missing node '{1}'.").format(
						binding.binding_key, binding.node_key
					)
				)

			if binding.input_name not in node.get("inputs", {}):
				frappe.throw(
					_("Workflow Binding '{0}' references missing input '{1}' on node '{2}'.").format(
						binding.binding_key, binding.input_name, binding.node_key
					)
				)
