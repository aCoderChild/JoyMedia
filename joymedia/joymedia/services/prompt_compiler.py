import hashlib
import json

import frappe
from frappe import _
from frappe.utils import now


@frappe.whitelist()
def compile_prompt_from_ui(shot_specification: str, prompt_template_version: str):
	compiled_prompt = compile_prompt(
		shot_specification=shot_specification,
		prompt_template_version=prompt_template_version,
	)
	frappe.db.commit()
	return {
		"name": compiled_prompt.name,
		"prompt_text": compiled_prompt.prompt_text,
	}


def compile_prompt(shot_specification: str, prompt_template_version: str):
	shot = frappe.get_doc("Shot Specification", shot_specification)
	media_spec = frappe.get_doc("Media Specification", shot.media_specification)
	template_version = frappe.get_doc("Prompt Template Version", prompt_template_version)

	snapshot = _build_source_snapshot(shot, media_spec)
	prompt_text = _render_template(template_version.template_body, snapshot)
	prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

	doc = frappe.get_doc(
		{
			"doctype": "Compiled Prompt",
			"shot_specification": shot.name,
			"prompt_template_version": template_version.name,
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
		"required_elements": getattr(media_spec, "required_elements", None) or "",
		"media_consistency_requirements": media_spec.consistency_requirements or "",
		"forbidden_elements": media_spec.forbidden_elements or "",
		"camera_direction": shot.camera_direction or "",
		"subject_identity": shot.subject_identity or "",
		"action_plot": shot.action_plot or "",
		"environment": shot.environment or "",
		"spatial_composition": shot.spatial_composition or "",
		"opening_state": shot.opening_state or "",
		"ending_state": shot.ending_state or "",
		"continuity_requirements": shot.continuity_requirements or "",
		"audio_direction": shot.audio_direction or "",
	}


def _render_template(template_body, values):
	if not template_body:
		frappe.throw(_("Prompt Template Body is empty."))
	try:
		prompt = template_body.format_map(_SafeFormatDict(values))
	except (KeyError, ValueError, IndexError) as exc:
		frappe.throw(_("Unable to compile prompt: {0}").format(str(exc)))
	return "\n".join(line.strip() for line in prompt.splitlines() if line.strip())


class _SafeFormatDict(dict):
	def __missing__(self, key):
		return ""
