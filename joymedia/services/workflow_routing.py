"""Automatic per-shot render strategy selection.

Customers describe a film and select references; they never choose a model.  This
module maps the references required by an individual shot to an immutable
workflow/pipeline combination and normalizes its input roles to that contract.
"""

from __future__ import annotations

import re

import frappe

from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow


FLUX_KEYFRAME_KEY = "flux_t2i_keyframe"
FLUX2_KEYFRAME_KEY = "flux2_klein_multireference_keyframe"


def automatic_planning_input_contract():
	"""Describe semantic inputs to the AI Director, independent of one graph.

	The Director should plan with the ingredients in the brief (person, products
	and place), rather than the narrow slots of whichever workflow happened to
	be the project's default. ``resolve_shot_render_route`` later chooses the
	concrete graph and enforces its real contract.
	"""
	return [
		{"role": "person", "accepted_media_type": "Image", "min_count": 0, "max_count": 1, "allow_multiple": False},
		{"role": "product", "accepted_media_type": "Image", "min_count": 0, "max_count": 1, "allow_multiple": False},
		{"role": "product_2", "accepted_media_type": "Image", "min_count": 0, "max_count": 1, "allow_multiple": False},
		{"role": "environment", "accepted_media_type": "Image", "min_count": 0, "max_count": 1, "allow_multiple": False},
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


def route_shot_references(references):
	"""Classify references and allocate deterministic workflow roles.

	A direct R2V workflow has exactly two scalar slots.  Flux 2 has explicit
	person/product/product_2/environment slots; any further material is composed
	into one reference board so an arbitrary source collection remains usable.
	"""
	normalized = []
	seen = {"person": 0, "product": 0, "environment": 0}
	for reference in references or []:
		if not reference or not reference.get("asset_version"):
			continue
		item = dict(reference)
		role = normalize_reference_role(item.get("reference_role") or item.get("input_role"))
		if role == "person" and not seen["person"]:
			assigned = "person"
			seen["person"] += 1
		elif role == "environment" and not seen["environment"]:
			assigned = "environment"
			seen["environment"] += 1
		elif role in {"product", "product_1"} and not seen["product"]:
			assigned = "product"
			seen["product"] += 1
		elif role in {"product", "product_1", "product_2"} and seen["product"] == 1:
			assigned = "product_2"
			seen["product"] += 1
		else:
			assigned = "reference_board"
		item["reference_role"] = assigned
		normalized.append(item)
	return normalized


def strategy_for_references(references, *, handoff_type="", motion_plan_json=""):
	"""Choose a strategy from the real contracts, not a guessed model limit."""
	raw_roles = [frappe.scrub(item.get("reference_role") or item.get("input_role") or "") for item in references or []]
	items = route_shot_references(references)
	count = len(items)
	product_count = sum(1 for item in items if item["reference_role"] in {"product", "product_2"})
	product_change = bool(re.search(
		r"product[_ -]?(?:change|switch|swap)|(?:switch|swap|replace).{0,40}product",
		f"{handoff_type} {motion_plan_json}",
		re.IGNORECASE,
	))
	if count == 0:
		return "flux_keyframe_i2v", items, "No image reference: create a Flux keyframe, then animate it."
	# R2V's actual binding contract has two required scalar image inputs.  It is
	# the fastest path only for a simple pair, not a generic 1–3-reference path.
	if count == 2 and (
		all(role == "product_reference" for role in raw_roles)
		or product_count < 2
	) and not product_change:
		return "direct_r2v", items, "Two simple references fit the direct R2V contract."
	if count == 1:
		return "flux_keyframe_i2v", items, "One reference is composed into a Flux keyframe before animation."
	return "flux2_multireference_i2v", items, (
		"Multiple reference conditions require Flux 2 composition before animation."
	)


def resolve_shot_render_route(default_workflow, references, *, handoff_type="", motion_plan_json=""):
	"""Return frozen workflow/pipeline identifiers and normalized references."""
	strategy, normalized, reason = strategy_for_references(
		references, handoff_type=handoff_type, motion_plan_json=motion_plan_json
	)
	tier = "turbo" if "turbo" in str(getattr(default_workflow, "workflow_key", "")).lower() else "production"
	if strategy == "direct_r2v":
		workflow = _latest_workflow(f"h3_r2v_{tier}") or default_workflow
		return _route(strategy, workflow, None, _as_r2v_references(normalized), reason)

	keyframe_key = FLUX2_KEYFRAME_KEY if strategy == "flux2_multireference_i2v" else FLUX_KEYFRAME_KEY
	final_key = f"h3_i2v_{tier}"
	pipeline = _pipeline_for(keyframe_key, final_key)
	# Flux 2 is an optional composition stage. Installations commonly have one
	# validated Flux 2 pipeline paired with the production I2V workflow even when
	# their default direct workflow is turbo. A valid composition route is safer
	# than rejecting a multi-reference shot solely because the preferred tier is
	# absent; preserve the requested tier whenever it is available.
	if not pipeline and strategy == "flux2_multireference_i2v":
		pipeline = _pipeline_for(keyframe_key, None)
	if not pipeline:
		frappe.throw(
			frappe._("No executable {0} pipeline is configured for the selected delivery tier.").format(strategy)
		)
	workflow = frappe.get_doc("Generation Workflow", pipeline.steps[-1].workflow)
	if strategy == "flux_keyframe_i2v":
		normalized = _as_flux_keyframe_references(normalized, pipeline)
	return _route(strategy, workflow, pipeline, normalized, reason)


def _route(strategy, workflow, pipeline, references, reason):
	return {
		"strategy": strategy,
		"workflow": workflow.name,
		"generation_pipeline": pipeline.name if pipeline else "",
		"references": references,
		"reason": reason,
		# A new product/multi-reference composition must run its keyframe stage;
		# it cannot safely skip directly to a prior shot's continuation frame.
		"requires_recomposition": strategy == "flux2_multireference_i2v",
	}


def _as_r2v_references(references):
	return [
		{**reference, "reference_role": "product_reference"}
		for reference in references[:2]
	]


def _as_flux_keyframe_references(references, pipeline):
	"""Map Flux's single generic reference onto its declared keyframe role."""
	from joymedia.services.generation_pipeline_service import get_pipeline_steps
	from joymedia.services.workflow_resolver import get_workflow_input_contract

	keyframe = frappe.get_doc("Generation Workflow", get_pipeline_steps(pipeline.name)[0].workflow)
	role = next(
		(
			item["role"]
			for item in get_workflow_input_contract(keyframe)
			if item.get("accepted_media_type") in {"Image", "Any"}
		),
		None,
	)
	if not role:
		frappe.throw(frappe._("Flux keyframe workflow has no image input role."))
	return [{**reference, "reference_role": role} for reference in references[:1]]


def _latest_workflow(workflow_key):
	return get_latest_valid_workflow(workflow_key)


def _pipeline_for(keyframe_key, final_key=None):
	"""Find the newest compatible immutable pipeline, preferring a requested I2V tier."""
	from joymedia.services.generation_pipeline_service import get_pipeline_steps

	for row in frappe.get_all(
		"Generation Pipeline",
		fields=["name", "version_number"],
		order_by="version_number desc, modified desc",
	):
		pipeline = frappe.get_doc("Generation Pipeline", row.name)
		steps = get_pipeline_steps(pipeline.name)
		if len(steps) < 2:
			continue
		first = frappe.get_doc("Generation Workflow", steps[0].workflow)
		last = frappe.get_doc("Generation Workflow", steps[-1].workflow)
		if first.workflow_key != keyframe_key:
			continue
		if final_key and last.workflow_key != final_key:
			continue
		if not final_key and not str(last.workflow_key or "").startswith("h3_i2v_"):
			continue
		if first.workflow_key == keyframe_key:
			return pipeline
	return None
