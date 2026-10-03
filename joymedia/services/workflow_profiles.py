import frappe
from frappe import _

from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow


def choose_shot_workflow(snapshot, shot):
	"""Choose an executable backend profile from frozen Shot inputs and settings."""
	references = shot.get("references") or []
	reference_mode = snapshot.get("reference_mode") or "Single Image"
	quality_mode = snapshot.get("quality_mode") or "Production"

	if reference_mode == "Multi-reference":
		if len(references) != 2:
			frappe.throw(
				_("Multi-reference Shots require exactly two ordered reference images; Shot {0} has {1}.").format(
					shot.get("shot_number"), len(references)
				)
			)
		workflow_key = "h3_r2v_turbo" if quality_mode == "Draft" else "h3_r2v_production"
	else:
		if len(references) != 1:
			frappe.throw(
				_("Single Image Shots require exactly one starting image; Shot {0} has {1}.").format(
					shot.get("shot_number"), len(references)
				)
			)
		short_workflow = get_latest_valid_workflow("h3_i2v_production")
		if not short_workflow:
			frappe.throw(_("No executable Single Image workflow is configured."))
		workflow_key = (
			"h3_sato_generation"
			if int(shot.get("planned_frame_count") or 0) > int(short_workflow.frame_count or 0)
			else "h3_i2v_production"
		)

	workflow = get_latest_valid_workflow(workflow_key)
	if not workflow:
		frappe.throw(_("No executable backend workflow is configured for {0}.").format(workflow_key))
	return workflow


def input_role_for_workflow(workflow):
	"""Return the user reference role expected by the selected initial profile."""
	return "product_reference" if workflow.workflow_key in ("h3_r2v_production", "h3_r2v_turbo") else "first_frame"
