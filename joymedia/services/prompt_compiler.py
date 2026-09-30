import hashlib

import frappe
from frappe import _


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
	return compile_prompt_for_documents(shot, media_spec)


def compile_segment_prompt(shot_specification: str, segment_index: int, segment_count: int):
	base = compile_prompt(shot_specification)
	if segment_count == 1:
		return base
	if segment_index == 1:
		return (
			f"{base}\n\nThis is segment 1 of {segment_count}. "
			"Begin the planned action naturally."
		).strip()
	return (
		f"{base}\n\nThis is continuation segment {segment_index} of {segment_count}. "
		"Continue directly from the supplied first frame. "
		"Do not restart or reintroduce the action."
	).strip()


def compile_prompt_for_documents(shot, media_spec):
	prompt = (shot.generation_prompt or "").strip()
	if not prompt:
		frappe.throw(
			_("Shot Specification {0} has no Qwen-generated generation_prompt.").format(shot.name)
		)

	if media_spec.continuity_mode in ("Continuous", "Consistency") and int(shot.shot_number or 0) > 1:
		prompt = (
			f"{prompt}\n\n"
			"Continuity: Continue naturally from the previous shot's generated last frame. "
			"Preserve the product geometry, color, orientation, and scene state. "
			"Describe the next movement from the existing pose rather than reintroducing "
			"the product from scratch."
		)
	return prompt.strip()


def _build_source_snapshot(shot, media_spec):
	return {
		"media_specification": media_spec.name,
		"shot_specification": shot.name,
		"generation_prompt": shot.generation_prompt or "",
	}
