"""Which workflow a scene uses and what input roles it accepts: the customer-facing contract of the promoted pipeline.
"""

import frappe
from frappe import _


def choose_shot_workflow(snapshot, shot):
	"""Use the exact per-shot workflow frozen into the project snapshot."""
	workflow_name = shot.get("workflow") or snapshot.get("workflow")
	if not workflow_name or not frappe.db.exists("Generation Workflow", workflow_name):
		frappe.throw(_("The project snapshot has no executable Generation Workflow."))
	return frappe.get_doc("Generation Workflow", workflow_name)


def input_role_for_workflow(workflow):
	"""Return the first image input role declared by a workflow's bindings."""
	from joymedia.services.workflows.resolver import get_workflow_input_contract

	for item in get_workflow_input_contract(workflow):
		if item.get("accepted_media_type") in ("Image", "Any"):
			return item["role"]
	return None


def references_for_workflow(workflow, references):
	"""Return references bounded only by the selected workflow's declared contract."""
	references = [reference for reference in references or [] if reference.get("asset_version")]
	from joymedia.services.workflows.resolver import get_workflow_input_contract

	role = input_role_for_workflow(workflow)
	contract = next((item for item in get_workflow_input_contract(workflow) if item["role"] == role), None)
	if not contract:
		return references[:1]
	maximum = int(contract.get("max_count") or 0)
	return references[:maximum] if maximum else references


def allowed_workflows_for_shot(snapshot, shot):
	"""Return the initial profile and its internal continuation profile for a Shot."""
	initial = choose_shot_workflow(snapshot, shot)
	continuation = (
		frappe.get_doc("Generation Workflow", initial.continuation_workflow)
		if initial.continuation_workflow else None
	)
	return tuple(workflow for workflow in (initial, continuation) if workflow)
