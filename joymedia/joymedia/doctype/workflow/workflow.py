# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document

from joymedia.workflow_adapters import get_workflow_adapter
from joymedia.workflow_adapters.base import canonical_workflow_json


IMMUTABLE_FIELDS = (
	"workflow_key",
	"version_number",
	"workflow_json",
	"bindings",
	"frame_count",
	"output_fps",
	"produces_video",
	"produces_audio",
)

DEFAULT_WORKFLOW_KEY = "product_showcase"


def get_latest_valid_workflow(workflow_key=None):
	"""Return the newest workflow whose stored graph and bindings are valid."""
	from joymedia.services.workflow_resolver import validate_workflow_bindings

	filters = {"workflow_key": workflow_key} if workflow_key else {}
	rows = frappe.get_all(
		"Workflow",
		filters=filters,
		fields=["name", "workflow_key", "version_number"],
		order_by="version_number desc, modified desc",
	)
	for row in rows:
		workflow = frappe.get_doc("Workflow", row.name)
		try:
			validate_workflow_bindings(workflow)
		except Exception:
			continue
		return workflow
	return None


@frappe.whitelist()
def validate_workflow(version_name: str):
	"""Validate an existing Workflow's dynamic bindings on demand."""
	frappe.has_permission("Workflow", "read", version_name, throw=True)
	workflow_version = frappe.get_doc("Workflow", version_name)
	from joymedia.services.workflow_resolver import validate_workflow_bindings

	validate_workflow_bindings(workflow_version)
	return {"valid": True, "workflow_version": workflow_version.name}


@frappe.whitelist()
def get_workflow_nodes(version_name: str):
	"""Return the node keys and available inputs from a stored ComfyUI API workflow."""
	frappe.has_permission("Workflow", "read", version_name, throw=True)
	workflow_version = frappe.get_doc("Workflow", version_name)
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

	return {"workflow": workflow_version.name, "nodes": nodes}


@frappe.whitelist()
def clone_workflow_as_draft(version_name: str):
	"""Create a new immutable revision of an existing Workflow."""
	frappe.has_permission("Workflow", "read", version_name, throw=True)
	frappe.has_permission("Workflow", "create", throw=True)
	workflow_version = frappe.get_doc("Workflow", version_name)

	clone = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_key": workflow_version.workflow_key,
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
	return {"name": clone.name, "version_number": clone.version_number}


@frappe.whitelist()
def set_default_workflow(version_name: str):
	"""Validate a workflow for compatibility with older Desk actions."""
	frappe.has_permission("Workflow", "read", version_name, throw=True)
	workflow_version = frappe.get_doc("Workflow", version_name)
	from joymedia.services.workflow_resolver import validate_workflow_bindings

	validate_workflow_bindings(workflow_version)
	return {
		"workflow": workflow_version.name,
	}


class Workflow(Document):
	def validate(self):
		self._set_backend_defaults()
		self._set_version_number()
		self._validate_immutable_content()
		workflow_data = frappe.parse_json(self.workflow_json)
		if not isinstance(workflow_data, dict):
			frappe.throw(_("Workflow JSON must define a JSON object."))

		from joymedia.services.workflow_resolver import validate_workflow_bindings

		validate_workflow_bindings(self)

		self.workflow_hash = hashlib.sha256(
			canonical_workflow_json(workflow_data).encode("utf-8")
		).hexdigest()

		for fieldname, value in get_workflow_adapter(self).extract_execution_metadata(
			workflow_data
		).items():
			setattr(self, fieldname, value)

	def _set_backend_defaults(self):
		if not self.workflow_key:
			self.workflow_key = DEFAULT_WORKFLOW_KEY

	def _set_version_number(self):
		if not self.is_new() or not self.workflow_key:
			return

		latest = frappe.get_all(
			"Workflow",
			filters={"workflow_key": self.workflow_key},
			fields=["version_number"],
			order_by="version_number desc",
			limit_page_length=1,
		)
		self.version_number = int(latest[0].version_number or 0) + 1 if latest else 1

	def _validate_immutable_content(self):
		previous = self.get_doc_before_save()
		if not previous:
			return

		changed_fields = [
			fieldname
			for fieldname in IMMUTABLE_FIELDS
			if self.has_value_changed(fieldname)
		]
		if not changed_fields:
			return
		frappe.throw(
			_("Workflow {0} is immutable after creation.").format(self.name)
		)
