import frappe
from frappe import _


SHOT_FIELDS = ("generation_prompt",)


def _get_editable_shot(project, shot_name):
	shot = frappe.get_doc("Shot Specification", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	return shot


@frappe.whitelist()
def revise_project_shot_with_ai(project_name, shot_name, instruction):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	instruction = (instruction or "").strip()
	if not instruction:
		frappe.throw(_("Describe the change you want to make to this shot."))
	shot = _get_editable_shot(project, shot_name)
	from joymedia.services.qwen_client import generate_shot_revision

	result = generate_shot_revision(
		instruction=instruction,
		shot=shot,
		product_name=project.product_name,
	)
	return {
		"shot_name": shot.name,
		"shot_number": shot.shot_number,
		"instruction": instruction,
		"summary": result["summary"],
		"changes": result["changes"],
		"generation_prompt": result["generation_prompt"],
	}


@frappe.whitelist()
def apply_project_shot_ai_revision(project_name, shot_name, values, regenerate=False):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if isinstance(values, str):
		values = frappe.parse_json(values)
	if not isinstance(values, dict):
		frappe.throw(_("AI shot changes must be a JSON object."))
	clean_values = {field: values.get(field, "") for field in SHOT_FIELDS}
	from joymedia.joymedia.doctype.media_project.media_project import update_project_shot, regenerate_project_shot

	result = update_project_shot(project_name, shot_name, clean_values)
	if frappe.parse_json(regenerate) if isinstance(regenerate, str) else regenerate:
		result["regeneration"] = regenerate_project_shot(project_name, shot_name)
	return result
