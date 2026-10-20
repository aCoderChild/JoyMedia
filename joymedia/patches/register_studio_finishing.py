"""Opt-in registration of the existing Studio graph, now declared as JSON."""

import json
from pathlib import Path

import frappe

GRAPH = Path(__file__).parents[1] / "workflow_adapters/graphs/studio_finish.json"


def execute():
	profile = json.loads(GRAPH.read_text())
	name = frappe.db.get_value(
		"Generation Workflow",
		{"workflow_key": profile["workflow_key"]},
		"name",
		order_by="version_number desc",
	)
	if name:
		stored = frappe.db.get_value(
			"Generation Workflow", name, ["workflow_json", "execution_spec"], as_dict=True
		)
		if (
			json.loads(stored.workflow_json) == profile["workflow_json"]
			and json.loads(stored.execution_spec) == profile["execution_spec"]
		):
			return name
	profile["workflow_json"] = json.dumps(profile["workflow_json"])
	profile["execution_spec"] = json.dumps(profile["execution_spec"])
	return frappe.get_doc(profile).insert(ignore_permissions=True).name
