"""AI-assisted edits of a scene: revise a shot from the user's feedback, apply the revision, rewrite a rejected
scene after QA, and polish the film idea.
"""

import frappe
from frappe import _

SHOT_FIELDS = ("generation_prompt", "image_prompt")


def _get_editable_shot(project, shot_name):
	shot = frappe.get_doc("Shot", shot_name)
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
	from joymedia.services.planning.llm import generate_shot_revision

	result = generate_shot_revision(
		instruction=instruction,
		shot=shot,
		product_name=project.product_name,
		video_idea=project.video_idea,
	)
	return {
		"shot_name": shot.name,
		"shot_number": shot.shot_number,
		"instruction": instruction,
		"summary": result["summary"],
		"changes": result["changes"],
		"generation_prompt": result["generation_prompt"],
		"image_prompt": result["image_prompt"],
	}


@frappe.whitelist()
def apply_project_shot_ai_revision(project_name, shot_name, values, regenerate=False):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if isinstance(values, str):
		values = frappe.parse_json(values)
	if not isinstance(values, dict):
		frappe.throw(_("AI shot changes must be a JSON object."))
	clean_values = {
		"generation_prompt": str(values.get("generation_prompt") or values.get("image_prompt") or "").strip(),
		"image_prompt": str(values.get("image_prompt") or values.get("generation_prompt") or "").strip(),
	}
	from joymedia.api.storyboard import regenerate_project_shot, update_project_shot

	result = update_project_shot(project_name, shot_name, clean_values)
	if frappe.parse_json(regenerate) if isinstance(regenerate, str) else regenerate:
		result["regeneration"] = regenerate_project_shot(project_name, shot_name)
	return result


@frappe.whitelist()
def improve_project_video_idea(project_name, current_idea=""):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	project._refuse_if_sheet()
	from joymedia.services.planning.llm import improve_video_idea
	from joymedia.services.project.context import _get_project_selected_assets, _meaningful_project_value

	references = _get_project_selected_assets(project)
	idea_text = (current_idea or "").strip() or project.video_idea or ""

	result = improve_video_idea(
		current_idea=idea_text,
		product_name=_meaningful_project_value(project.product_name, "the product"),
		references=references,
		duration=float(project.total_duration_seconds or 15),
		delivery_preset=project.delivery_preset or "Landscape",
	)

	improved_idea = result.get("improved_idea") or idea_text
	return {
		"project_name": project.name,
		"original_idea": idea_text,
		"improved_idea": improved_idea,
	}
