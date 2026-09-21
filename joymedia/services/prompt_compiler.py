import hashlib
import json

import frappe
from frappe.utils import now

from joymedia.workflow_adapters import get_workflow_adapter


@frappe.whitelist()
def compile_prompt_from_ui(shot_specification: str):
	compiled_prompt = compile_prompt(shot_specification=shot_specification)
	frappe.db.commit()
	return {
		"name": compiled_prompt.name,
		"prompt_text": compiled_prompt.prompt_text,
	}


def compile_prompt(shot_specification: str):
	shot = frappe.get_doc("Shot Specification", shot_specification)
	media_spec = frappe.get_doc("Media Specification", shot.media_specification)
	workflow_profile = frappe.get_doc("Workflow Profile", media_spec.workflow_profile)
	adapter = get_workflow_adapter(workflow_profile)

	snapshot = _build_source_snapshot(shot, media_spec)
	prompt_text = adapter.compile_prompt(shot, media_spec)
	prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

	doc = frappe.get_doc(
		{
			"doctype": "Compiled Prompt",
			"shot_specification": shot.name,
			"prompt_text": prompt_text,
			"compiled_at": now(),
			"source_snapshot_json": json.dumps(snapshot, ensure_ascii=False, indent=2),
			"prompt_hash": prompt_hash,
		}
	)
	doc.insert()
	return doc


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
