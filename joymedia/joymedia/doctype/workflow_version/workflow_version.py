# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
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

WORKFLOW_VALUE_PATHS = {
	"execution_width": ("minimax_cond", "inputs", "width"),
	"execution_height": ("minimax_cond", "inputs", "height"),
	"frame_count": ("minimax_cond", "inputs", "length"),
	"output_fps": ("save_video", "inputs", "frame_rate"),
}


class WorkflowVersion(Document):
	def validate(self):
		workflow_data = frappe.parse_json(self.workflow_json)
		derived_values = {
			fieldname: self._get_value(workflow_data, WORKFLOW_VALUE_PATHS.get(fieldname))
			for fieldname in H3_DEFAULTS
		}

		profile = frappe.db.get_value(
			"Workflow Profile",
			self.workflow_profile,
			["profile_name", "workflow_code"],
			as_dict=True,
		)
		profile_identity = ""
		if profile:
			profile_identity = f"{profile.profile_name or ''} {profile.workflow_code or ''}".lower()

		for fieldname, default in H3_DEFAULTS.items():
			value = derived_values[fieldname]
			if value is None and "h3" in profile_identity:
				value = default
			if value is not None:
				setattr(self, fieldname, value)

	@staticmethod
	def _get_value(data, path):
		if not path:
			return None
		for key in path:
			if not isinstance(data, dict) or key not in data:
				return None
			data = data[key]
		return data
