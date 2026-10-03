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
	"adapter_key",
	"continuation_workflow",
	"workflow_json",
	"bindings",
	"frame_count",
	"output_fps",
	"produces_video",
	"produces_audio",
)

DEFAULT_WORKFLOW_KEY = "product_showcase"
DEFAULT_ADAPTER_KEY = "minimax_h3"


def get_latest_valid_workflow(workflow_key=None):
	"""Return the newest workflow whose stored graph and bindings are executable."""
	from joymedia.services.workflow_resolver import (
		validate_workflow_bindings,
		validate_workflow_for_execution,
	)

	filters = {"workflow_key": workflow_key} if workflow_key else {}
	rows = frappe.get_all(
		"Generation Workflow",
		filters=filters,
		fields=["name", "workflow_key", "version_number"],
		order_by="version_number desc, modified desc",
	)
	for row in rows:
		workflow = frappe.get_doc("Generation Workflow", row.name)
		try:
			get_workflow_adapter(workflow)
			validate_workflow_bindings(workflow)
			validate_workflow_for_execution(workflow)
			if workflow.workflow_key == DEFAULT_WORKFLOW_KEY and not any(
				binding.binding_key == "first_frame"
				and binding.required
				and binding.required_input_role
				for binding in workflow.bindings
			):
				continue
		except Exception:
			continue
		return workflow
	return None


@frappe.whitelist()
def validate_workflow(version_name: str):
	"""Validate an existing Generation Workflow on demand."""
	frappe.has_permission("Generation Workflow", "read", version_name, throw=True)
	workflow = frappe.get_doc("Generation Workflow", version_name)
	from joymedia.services.workflow_resolver import (
		validate_workflow_bindings,
		validate_workflow_for_execution,
	)

	get_workflow_adapter(workflow)
	validate_workflow_bindings(workflow)
	validate_workflow_for_execution(workflow)
	return {"valid": True, "workflow": workflow.name}


@frappe.whitelist()
def get_workflow_nodes(version_name: str):
	"""Return node keys and available inputs from the stored ComfyUI API workflow."""
	frappe.has_permission("Generation Workflow", "read", version_name, throw=True)
	workflow = frappe.get_doc("Generation Workflow", version_name)
	workflow = frappe.parse_json(workflow.workflow_json)
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

	return {"workflow": workflow.name, "nodes": nodes}


@frappe.whitelist()
def clone_workflow_as_draft(version_name: str):
	"""Create a new immutable revision of an existing Generation Workflow."""
	frappe.has_permission("Generation Workflow", "read", version_name, throw=True)
	frappe.has_permission("Generation Workflow", "create", throw=True)
	workflow = frappe.get_doc("Generation Workflow", version_name)

	clone = frappe.get_doc(
		{
			"doctype": "Generation Workflow",
			"workflow_key": workflow.workflow_key,
			"adapter_key": workflow.adapter_key,
			"workflow_json": workflow.workflow_json,
		}
	)
	for binding in workflow.bindings:
		clone.append(
			"bindings",
			{
				"binding_key": binding.binding_key,
				"node_key": binding.node_key,
				"input_name": binding.input_name,
				"required_input_role": binding.required_input_role,
				"value_type": binding.value_type,
				"required": binding.required,
				"accepted_media_type": getattr(binding, "accepted_media_type", None) or "Any",
				"allow_multiple": getattr(binding, "allow_multiple", 0),
			},
		)
	clone.insert()
	return {"name": clone.name, "version_number": clone.version_number}


class GenerationWorkflow(Document):
	def validate(self):
		self._set_defaults()
		self._set_version_number()
		self._validate_immutable_content()
		workflow_data = frappe.parse_json(self.workflow_json)
		if not isinstance(workflow_data, dict):
			frappe.throw(_("Workflow JSON must define a JSON object."))

		from joymedia.services.workflow_resolver import validate_workflow_bindings

		adapter = get_workflow_adapter(self)
		validate_workflow_bindings(self)
		self.workflow_hash = hashlib.sha256(
			canonical_workflow_json(workflow_data).encode("utf-8")
		).hexdigest()

		for fieldname, value in adapter.extract_execution_metadata(workflow_data).items():
			setattr(self, fieldname, value)

	def _set_defaults(self):
		if not self.workflow_key:
			self.workflow_key = DEFAULT_WORKFLOW_KEY
		if not self.adapter_key:
			self.adapter_key = DEFAULT_ADAPTER_KEY

	def _set_version_number(self):
		if not self.is_new() or not self.workflow_key:
			return

		latest = frappe.get_all(
			"Generation Workflow",
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
			_("Generation Workflow {0} is immutable after creation.").format(self.name)
		)
