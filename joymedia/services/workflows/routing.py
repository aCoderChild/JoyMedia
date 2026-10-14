"""Promoted-pipeline reference binding for storyboard shots.

Customers describe a film and select references; they never select a model.
The site administrator promotes one immutable, linear production pipeline and this
module only validates and binds a shot to that published contract.
"""

from __future__ import annotations

import frappe


def automatic_planning_input_contract():
	"""Describe semantic inputs to the AI Director, independent of one graph.

	The Director should plan with the ingredients in the brief (person, products
	and place), rather than the narrow slots of whichever workflow happened to
	be the project's default. ``resolve_shot_render_route`` later chooses the
	concrete graph and enforces its real contract.
	"""
	return [
		{"role": "person", "accepted_media_type": "Image", "min_count": 0, "max_count": 0, "allow_multiple": True},
		{"role": "product", "accepted_media_type": "Image", "min_count": 0, "max_count": 0, "allow_multiple": True},
		{"role": "environment", "accepted_media_type": "Image", "min_count": 0, "max_count": 0, "allow_multiple": True},
		{"role": "reference_board", "accepted_media_type": "Image", "min_count": 0, "max_count": 0, "allow_multiple": True},
	]


def normalize_reference_role(value):
	"""Return a stable semantic role while retaining numbered product slots."""
	role = frappe.scrub(value or "general")
	aliases = {
		"character": "person",
		"people": "person",
		"talent": "person",
		"person_reference": "person",
		"place": "environment",
		"background": "environment",
		"environment_reference": "environment",
		"product_reference": "r2v_reference",
		"keyframe_reference": "general",
	}
	return aliases.get(role, role or "general")


def resolve_shot_render_route(default_workflow, references, *, handoff_type="", motion_plan_json="", pipeline_name=None):
	"""Return the one configured production pipeline for a shot.

	Reference quantity never selects a model.  The first stage's declared binding
	contract decides whether the selected references can be supplied; otherwise the
	project is stopped with an actionable error instead of discarding identities.
	"""
	from joymedia.services.workflows.pipeline import get_active_generation_pipeline, get_pipeline_steps
	from joymedia.services.workflows.resolver import get_workflow_input_contract

	try:
		pipeline = frappe.get_doc("Generation Pipeline", pipeline_name) if pipeline_name else get_active_generation_pipeline()
	except frappe.ValidationError as exc:
		# Storyboards remain editable before an operator promotes a pipeline. This
		# is not a rendering fallback: MediaProject.generate_video requires the
		# promoted pipeline before it can create a Generation Run.
		if pipeline_name or "No active Generation Pipeline is configured" not in str(exc):
			raise
		contract = {item["role"]: item for item in get_workflow_input_contract(default_workflow)}
		return {
			"strategy": "unpromoted_workflow",
			"workflow": default_workflow.name,
			"generation_pipeline": "",
			"references": _map_pipeline_references(references, contract),
			"reason": "Storyboard draft awaiting an explicitly promoted production pipeline.",
			"requires_recomposition": str(handoff_type or "").casefold() in {"new_scene", "new scene", "scene_reset"},
		}
	steps = get_pipeline_steps(pipeline.name)
	if len(steps) < 2:
		frappe.throw(frappe._("The active Generation Pipeline must contain at least two ordered stages."))
	workflow = frappe.get_doc("Generation Workflow", steps[-1].workflow)
	keyframe = frappe.get_doc("Generation Workflow", steps[0].workflow)
	contract = {item["role"]: item for item in get_workflow_input_contract(keyframe)}
	normalized = _map_pipeline_references(references, contract)
	new_scene = str(handoff_type or "").casefold() in {"new_scene", "new scene", "scene_reset"}
	return {
		"strategy": "promoted_linear_pipeline",
		"workflow": workflow.name,
		"generation_pipeline": pipeline.name,
		"references": normalized,
		"reason": "Configured promoted production pipeline.",
		"requires_recomposition": new_scene,
	}


def _map_pipeline_references(references, contract):
	"""Map every selected visual reference to a declared first-stage role."""
	if not references:
		return []
	board = contract.get("reference_board") or contract.get("product_reference")
	board_role = "reference_board" if "reference_board" in contract else "product_reference"
	mapped = []
	for reference in references:
		item = dict(reference)
		declared = frappe.scrub(item.get("reference_role") or item.get("input_role") or "")
		# A role the first stage declares itself (person and character are different inputs) is kept as it is.
		role = declared if declared in contract else normalize_reference_role(declared)
		if role == "logo":
			# Logos are pasted over the keyframe, so no image stage needs a binding for them.
			item["reference_role"] = role
		elif role in contract:
			item["reference_role"] = role
		elif board and board.get("allow_multiple"):
			item["reference_role"] = board_role
		else:
			frappe.throw(
				frappe._("The active pipeline's first-stage workflow has no binding for reference role '{0}'. ")
				.format(role)
				+ frappe._("Configure a multi-reference binding or remove that reference explicitly.")
			)
		mapped.append(item)
	return mapped
