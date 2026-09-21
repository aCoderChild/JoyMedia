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
	"change_notes",
	"bindings",
	"frame_count",
	"output_fps",
	"produces_video",
	"produces_audio",
)


@frappe.whitelist()
def validate_workflow_version(version_name: str):
	"""Validate an existing Workflow Version's dynamic bindings on demand."""
	frappe.has_permission("Workflow Version", "read", version_name, throw=True)
	workflow_version = frappe.get_doc("Workflow Version", version_name)
	from joymedia.services.workflow_resolver import validate_workflow_bindings

	validate_workflow_bindings(workflow_version)
	return {"valid": True, "workflow_version": workflow_version.name}


@frappe.whitelist()
def get_workflow_nodes(version_name: str):
	"""Return the node keys and available inputs from a stored ComfyUI API workflow."""
	frappe.has_permission("Workflow Version", "read", version_name, throw=True)
	workflow_version = frappe.get_doc("Workflow Version", version_name)
	workflow = frappe.parse_json(workflow_version.workflow_json)
	if not isinstance(workflow, dict):
		frappe.throw(_("Workflow JSON must define a JSON object."))

	nodes = []
	for node_key, node in workflow.items():
		if not isinstance(node, dict):
			continue
		inputs = node.get("inputs") or {}
		meta = node.get("_meta") or {}
		nodes.append(
			{
				"node_key": str(node_key),
				"class_type": node.get("class_type") or "",
				"title": meta.get("title") or "",
				"inputs": sorted(inputs.keys()) if isinstance(inputs, dict) else [],
			}
		)

	return {"workflow_version": workflow_version.name, "nodes": nodes}


@frappe.whitelist()
def clone_workflow_version_as_draft(version_name: str):
	"""Create an editable Draft copy of an existing version, including its bindings."""
	frappe.has_permission("Workflow Version", "read", version_name, throw=True)
	frappe.has_permission("Workflow Version", "create", throw=True)
	workflow_version = frappe.get_doc("Workflow Version", version_name)

	latest = frappe.get_all(
		"Workflow Version",
		filters={"workflow_profile": workflow_version.workflow_profile},
		fields=["version_number"],
		order_by="version_number desc",
		limit_page_length=1,
	)
	next_version = int(latest[0].version_number or 0) + 1 if latest else 1
	clone = frappe.get_doc(
		{
			"doctype": "Workflow Version",
			"workflow_profile": workflow_version.workflow_profile,
			"version_number": next_version,
			"version_label": _("{0} - Draft {1}").format(
				workflow_version.version_label, next_version
			),
			"status": "Draft",
			"workflow_json": workflow_version.workflow_json,
		}
	)
	for binding in workflow_version.bindings:
		clone.append(
			"bindings",
			{
				"binding_key": binding.binding_key,
				"node_key": binding.node_key,
				"input_name": binding.input_name,
				"value_source": binding.value_source,
				"required_input_role": binding.required_input_role,
				"value_type": binding.value_type,
				"required": binding.required,
				"allow_override": binding.allow_override,
				"description": binding.description,
			},
		)
	clone.insert()
	return {"name": clone.name, "version_number": clone.version_number, "status": clone.status}


@frappe.whitelist()
def set_default_workflow_version(version_name: str):
	"""Validate and make a Testing/Production Workflow Version the profile default."""
	frappe.has_permission("Workflow Version", "read", version_name, throw=True)
	workflow_version = frappe.get_doc("Workflow Version", version_name)
	frappe.has_permission(
		"Workflow Profile", "write", workflow_version.workflow_profile, throw=True
	)
	if workflow_version.status not in ("Testing", "Production"):
		frappe.throw(_("Only Testing or Production Workflow Versions can be set as default."))

	from joymedia.services.workflow_resolver import validate_workflow_bindings

	validate_workflow_bindings(workflow_version)
	profile = frappe.get_doc("Workflow Profile", workflow_version.workflow_profile)
	profile.default_workflow_version = workflow_version.name
	profile.save()
	return {
		"workflow_profile": profile.name,
		"default_workflow_version": workflow_version.name,
	}


class WorkflowVersion(Document):
	def validate(self):
		self._validate_immutable_content()
		workflow_data = frappe.parse_json(self.workflow_json)
		if not isinstance(workflow_data, dict):
			frappe.throw(_("Workflow JSON must define a JSON object."))

		# Drafts may be incomplete while an operator repairs imported workflow JSON
		# and bindings. A version must be internally consistent before it can be
		# tested or promoted to production.
		if self.status in ("Testing", "Production"):
			from joymedia.services.workflow_resolver import validate_workflow_bindings

			validate_workflow_bindings(self)

		self.workflow_hash = hashlib.sha256(
			canonical_workflow_json(workflow_data).encode("utf-8")
		).hexdigest()

		profile = frappe.get_doc("Workflow Profile", self.workflow_profile)
		for fieldname, value in get_workflow_adapter(profile).extract_execution_metadata(
			workflow_data
		).items():
			setattr(self, fieldname, value)

	def _validate_immutable_content(self):
		previous = self.get_doc_before_save()
		if not previous or previous.status not in IMMUTABLE_STATUSES:
			return

		changed_fields = [
			fieldname
			for fieldname in IMMUTABLE_FIELDS
			if self.has_value_changed(fieldname)
		]
		if not changed_fields and self.status == previous.status:
			return
		if (
			previous.status == "Production"
			and self.status == "Deprecated"
			and not changed_fields
		):
			return
		frappe.throw(
			_("Workflow Version {0} is immutable after it is {1}.").format(
				self.name, previous.status
			)
		)
