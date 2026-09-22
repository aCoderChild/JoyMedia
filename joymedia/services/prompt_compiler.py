import hashlib

import frappe

from joymedia.workflow_adapters import get_workflow_adapter


@frappe.whitelist()
def compile_prompt_from_ui(shot_specification: str):
	prompt_text = compile_prompt(shot_specification=shot_specification)
	return {
		"prompt_text": prompt_text,
		"prompt_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
	}


def compile_prompt(shot_specification: str):
	shot = frappe.get_doc("Shot Specification", shot_specification)
	media_spec = frappe.get_doc("Media Specification", shot.media_specification)
	if shot.generation_prompt:
		return shot.generation_prompt.strip()

	workflow = frappe.get_doc("Workflow", media_spec.workflow)
	adapter = get_workflow_adapter(workflow)
	return adapter.compile_prompt(shot, media_spec)


def _build_source_snapshot(shot, media_spec):
	return {
		"media_specification": media_spec.name,
		"shot_specification": shot.name,
		"generation_instructions": media_spec.generation_instructions or "",
		"camera_direction": shot.camera_direction or "",
		"subject_identity": shot.subject_identity or "",
		"action_plot": shot.action_plot or "",
		"environment": shot.environment or "",
		"audio_direction": shot.audio_direction or "",
	}
