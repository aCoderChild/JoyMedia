import frappe
from frappe import _

from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow
from joymedia.services.generation_pipeline_service import pipeline_for_final_workflow, get_pipeline_steps
from joymedia.workflow_adapters import get_workflow_adapter


def customer_workflow_key(reference_mode, quality_mode):
	"""Legacy compatibility shim; workflow selection now belongs to Project settings."""
	return None


def choose_shot_workflow(snapshot, shot):
	"""Use the exact workflow frozen into the project snapshot."""
	workflow_name = snapshot.get("workflow")
	if not workflow_name or not frappe.db.exists("Generation Workflow", workflow_name):
		frappe.throw(_("The project snapshot has no executable Generation Workflow."))
	return frappe.get_doc("Generation Workflow", workflow_name)


def input_role_for_workflow(workflow):
	"""Return the first image input role declared by a workflow's bindings."""
	from joymedia.services.workflow_resolver import get_workflow_input_contract

	for item in get_workflow_input_contract(workflow):
		if item.get("accepted_media_type") in ("Image", "Any"):
			return item["role"]
	return None


def references_for_workflow(workflow, references):
	"""Return references bounded only by the selected workflow's declared contract."""
	references = [reference for reference in references or [] if reference.get("asset_version")]
	from joymedia.services.workflow_resolver import get_workflow_input_contract

	role = input_role_for_workflow(workflow)
	contract = next((item for item in get_workflow_input_contract(workflow) if item["role"] == role), None)
	if not contract or not contract.get("allow_multiple"):
		return references[:1]
	maximum = int(contract.get("max_count") or 0)
	return references[:maximum] if maximum else references


def planning_input_contract(workflow, pipeline_name=None):
	"""Return the reference contract used while planning a pipeline-backed shot.

	The final workflow may consume an upstream artifact such as ``first_frame``.
	That is pipeline internals, not a user-upload requirement, so planning uses
	the initial pipeline step's contract.
	"""
	from joymedia.services.workflow_resolver import get_workflow_input_contract

	contract = get_workflow_input_contract(workflow)
	pipeline = frappe.get_doc("Generation Pipeline", pipeline_name) if pipeline_name else pipeline_for_final_workflow(workflow.name)
	if pipeline and (not pipeline.steps or pipeline.steps[-1].workflow != workflow.name):
		frappe.throw(_("Generation Pipeline {0} does not end with Workflow {1}.").format(
			pipeline.name, workflow.name
		))
	if not pipeline:
		return contract

	steps = get_pipeline_steps(pipeline.name)
	keyframe_workflow = frappe.get_doc("Generation Workflow", steps[0].workflow)
	keyframe_contract = get_workflow_input_contract(keyframe_workflow)
	# Only expose keyframe workflow inputs to the planner. ``first_frame`` is an
	# internal artifact produced by this step and consumed by the final video
	# workflow; it is not a reference the user must upload or the planner should
	# attach to each shot.
	return [item for item in keyframe_contract if item.get("role") != "first_frame"]


def allowed_workflows_for_shot(snapshot, shot):
	"""Return the initial profile and its internal continuation profile for a Shot."""
	initial = choose_shot_workflow(snapshot, shot)
	continuation = None
	if initial.continuation_workflow:
		continuation = frappe.get_doc("Generation Workflow", initial.continuation_workflow)
	else:
		adapter = get_workflow_adapter(initial)
		continuation_key = getattr(adapter, "continuation_workflow_key", None)
		if continuation_key:
			continuation = get_latest_valid_workflow(continuation_key)
	return tuple(workflow for workflow in (initial, continuation) if workflow)
