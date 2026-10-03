import hashlib
import json
from pathlib import Path

import frappe

from joymedia.workflow_adapters.base import canonical_workflow_json


WORKFLOW_SPECS = (
	{
		"filename": "minimax_h3_i2v_production.json",
		"workflow_key": "h3_i2v_production",
		"adapter_key": "minimax_h3_i2v",
		"bindings": (
			{
				"binding_key": "generation_prompt",
				"node_key": "105:104",
				"input_name": "prompt",
				"value_type": "Text",
				"required": 1,
			},
			{
				"binding_key": "first_frame",
				"node_key": "114",
				"input_name": "image",
				"required_input_role": "first_frame",
				"value_type": "File Path",
				"required": 1,
				"accepted_media_type": "Image",
			},
		),
	},
	{
		"filename": "minimax_h3_r2v_official.json",
		"workflow_key": "h3_r2v_production",
		"adapter_key": "minimax_h3_r2v",
		"bindings": (
			{
				"binding_key": "generation_prompt",
				"node_key": "138",
				"input_name": "value",
				"value_type": "Text",
				"required": 1,
			},
			{
				"binding_key": "reference_image_1",
				"node_key": "137",
				"input_name": "image",
				"required_input_role": "product_reference",
				"value_type": "File Path",
				"required": 1,
				"accepted_media_type": "Image",
			},
			{
				"binding_key": "reference_image_2",
				"node_key": "139",
				"input_name": "image",
				"required_input_role": "product_reference",
				"value_type": "File Path",
				"required": 1,
				"accepted_media_type": "Image",
			},
		),
	},
	{
		"filename": "minimax_h3_r2v_turbo4.json",
		"workflow_key": "h3_r2v_turbo",
		"adapter_key": "minimax_h3_r2v",
		"bindings": (
			{
				"binding_key": "generation_prompt",
				"node_key": "138",
				"input_name": "value",
				"value_type": "Text",
				"required": 1,
			},
			{
				"binding_key": "reference_image_1",
				"node_key": "137",
				"input_name": "image",
				"required_input_role": "product_reference",
				"value_type": "File Path",
				"required": 1,
				"accepted_media_type": "Image",
			},
			{
				"binding_key": "reference_image_2",
				"node_key": "139",
				"input_name": "image",
				"required_input_role": "product_reference",
				"value_type": "File Path",
				"required": 1,
				"accepted_media_type": "Image",
			},
		),
	},
)


def execute():
	registered = {}
	for spec in WORKFLOW_SPECS:
		registered[spec["workflow_key"]] = _register_workflow(spec)
	continuation = frappe.db.get_value(
		"Generation Workflow", {"workflow_key": "h3_sato_continuation"}, "name",
		order_by="version_number desc, modified desc",
	)
	if continuation:
		for workflow_key in ("h3_r2v_production", "h3_r2v_turbo"):
			workflow_name = registered.get(workflow_key)
			if workflow_name:
				frappe.db.set_value(
					"Generation Workflow", workflow_name, "continuation_workflow", continuation,
					update_modified=False,
				)


def _register_workflow(spec):
	workflow_path = Path(__file__).resolve().parent.parent / "workflows" / "minimax_h3" / spec["filename"]
	if not workflow_path.exists():
		raise FileNotFoundError(f"Missing workflow file: {workflow_path}")

	workflow_data = json.loads(workflow_path.read_text(encoding="utf-8"))
	expected_hash = hashlib.sha256(
		canonical_workflow_json(workflow_data).encode("utf-8")
	).hexdigest()

	existing = frappe.get_all(
		"Generation Workflow",
		filters={
			"workflow_key": spec["workflow_key"],
			"workflow_hash": expected_hash,
		},
		fields=["name"],
		order_by="version_number desc",
	)
	for row in existing:
		doc = frappe.get_doc("Generation Workflow", row.name)
		if doc.adapter_key == spec["adapter_key"] and _bindings_match(doc.bindings, spec["bindings"]):
			return doc.name

	doc = frappe.get_doc(
		{
			"doctype": "Generation Workflow",
			"workflow_key": spec["workflow_key"],
			"adapter_key": spec["adapter_key"],
			"workflow_json": json.dumps(workflow_data, indent=2, ensure_ascii=False),
		}
	)
	for binding in spec["bindings"]:
		doc.append("bindings", dict(binding))
	doc.insert(ignore_permissions=True)
	return doc.name


def _bindings_match(existing, expected):
	fields = (
		"binding_key",
		"node_key",
		"input_name",
		"required_input_role",
		"value_type",
		"required",
		"accepted_media_type",
		"allow_multiple",
	)
	def normalize(row, getter):
		values = {field: getter(row, field) for field in fields}
		values["required_input_role"] = values["required_input_role"] or ""
		values["accepted_media_type"] = values["accepted_media_type"] or "Any"
		values["required"] = int(bool(values["required"]))
		values["allow_multiple"] = int(bool(values["allow_multiple"]))
		return values

	return [
		normalize(row, lambda value, field: getattr(value, field, None))
		for row in existing
	] == [
		normalize(row, lambda value, field: value.get(field))
		for row in expected
	]
