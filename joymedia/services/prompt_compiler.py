import hashlib

import frappe
from frappe import _


def compile_prompt_from_ui(shot: str):
	prompt_text = compile_prompt(shot=shot)
	return {
		"prompt_text": prompt_text,
		"prompt_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
	}


def compile_prompt(shot: str):
	shot = frappe.get_doc("Shot", shot)
	project = frappe.get_doc("Media Project", shot.media_project)
	return compile_prompt_for_documents(shot, project)


def compile_segment_prompt(shot: str, segment_index: int, segment_count: int):
	base = compile_prompt(shot)
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


def compile_segment_prompt_from_snapshot(shot, project, segment_index: int, segment_count: int):
	asset_versions = _reference_asset_versions_from_snapshot(shot, project)
	# Multi-reference prompts are written by the director planner, which already
	# folded the global instructions into each take. Appending the whole-film
	# brief again makes the model render every place in one take as a montage.
	base = compile_prompt_for_documents(shot, project, include_global_instructions=not asset_versions)
	if asset_versions:
		from .film_director import describe_reference_tags, reference_preamble

		if segment_index == 1:
			base = f"{reference_preamble(asset_versions, project.get('references') or [])}\n\n{base}"
		else:
			# Continuation workflows receive only the previous frames, not the references.
			base = describe_reference_tags(base)
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


def compile_prompt_for_documents(shot, project, include_global_instructions=True):
	prompt = (shot.generation_prompt or "").strip()
	if not prompt:
		frappe.throw(
			_("Shot {0} has no Qwen-generated generation_prompt.").format(shot.name)
		)

	global_instructions = str(project.get("global_instructions") or "").strip()
	if global_instructions and include_global_instructions:
		prompt = (
			f"{prompt}\n\n"
			"Global instructions that apply to every shot:\n"
			f"{global_instructions}"
		)

	generation_mode = project.get("generation_mode")
	if generation_mode in ("Continuous", "Consistency") and int(shot.shot_number or 0) > 1:
		prompt = (
			f"{prompt}\n\n"
			"Continuity: Continue naturally from the previous shot's generated last frame. "
			"Preserve the product geometry, color, orientation, and scene state. "
			"Describe the next movement from the existing pose rather than reintroducing "
			"the product from scratch."
		)
	return prompt.strip()


def _reference_asset_versions_from_snapshot(shot, snapshot):
	"""Return a Reference-to-Video shot's ordered Asset Versions (<Picture 1>, <Picture 2>...)."""
	if snapshot.get("reference_mode") != "Multi-reference":
		return []
	snapshot_shot = next(
		(item for item in snapshot.get("shots") or [] if item.get("shot") == shot.name),
		None,
	)
	if not snapshot_shot:
		return []
	return [
		reference.get("asset_version")
		for reference in snapshot_shot.get("references") or []
		if reference.get("asset_version")
	]


def _build_source_snapshot(shot, project):
	return {
		"media_project": project.name,
		"shot": shot.name,
		"generation_prompt": shot.generation_prompt or "",
		"global_instructions": project.get("global_instructions") or "",
	}
