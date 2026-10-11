import hashlib
import json

import frappe


from frappe import _


PROMPT_SOURCES = {"image", "motion", "creative"}


def prompt_source_for_workflow(workflow, configured_source=None):
	"""Return a semantic prompt intent without knowing a workflow's model family."""
	source = str(configured_source or "").strip().lower()
	if source in PROMPT_SOURCES:
		return source
	return "image" if getattr(workflow, "output_media_type", None) == "Image" else "motion"


def _motion_plan(shot):
	value = getattr(shot, "motion_plan_json", None)
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			return []
	if isinstance(value, dict):
		value = value.get("actions")
	return value if isinstance(value, list) else []


def temporal_timing_instruction(shot, is_final=False, start_seconds=None, end_seconds=None):
	"""Compile a stored seconds-based plan into concise model guidance.

	Seconds are the creative contract.  Frame counts remain execution details in
	ComfyUI and are deliberately not mentioned to a text-to-video model.
	"""
	actions = _motion_plan(shot)
	if not actions:
		return ""
	parts = []
	for action in actions:
		try:
			start, end = float(action["start"]), float(action["end"])
		except (KeyError, TypeError, ValueError):
			continue
		text = str(action.get("action") or "").strip()
		if not text:
			continue
		if start_seconds is not None or end_seconds is not None:
			window_start = float(start_seconds or 0)
			window_end = float(end_seconds) if end_seconds is not None else end
			start, end = max(start, window_start), min(end, window_end)
			if end <= start:
				continue
			parts.append(f"{start - window_start:g}-{end - window_start:g}s: {text}")
		else:
			parts.append(f"{start:g}-{end:g}s: {text}")
	if not parts:
		return ""
	handoff = str(getattr(shot, "handoff_type", None) or "").strip()
	end_state = str(getattr(shot, "end_state", None) or "").strip()
	ending = "Conclude the whole film in the stated end state; settle and hold the final composition. Do not prepare another shot, transition, or new action." if is_final or handoff == "ending" else (
		f"Finish in this handoff state: {end_state}. Continue as a {handoff or 'motion_continuation'} into the next shot."
	)
	return "Chronological action plan (approximate timing): " + "; ".join(parts) + ". " + ending


def segment_action_timing_instruction():
	"""Compatibility text for callers outside a concrete shot context."""
	return "Use the shot's seconds-based action plan; keep one continuous action and a natural handoff."


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


def compile_segment_prompt(shot: str, segment_index: int, segment_count: int, prompt_source="motion", is_final=False):
	doc = frappe.get_doc("Shot", shot)
	project = frappe.get_doc("Media Project", doc.media_project)
	base = compile_prompt_for_documents(doc, project, prompt_source=prompt_source, is_final=is_final)
	if segment_count == 1:
		return base
	if segment_index == 1:
		return (
			f"{base}\n\nThis is segment 1 of {segment_count}. "
			"Begin the planned action naturally.\n\n"
			f"{temporal_timing_instruction(doc, is_final=is_final)}"
		).strip()
	return (
		f"{base}\n\nThis is continuation segment {segment_index} of {segment_count}. "
		"Continue directly from the supplied first frame, which is the last frame of the previous segment. "
		"Do not restart or reintroduce the action.\n\n"
		f"{temporal_timing_instruction(doc, is_final=is_final)}"
	).strip()


def compile_segment_prompt_from_snapshot(
	shot,
	project,
	segment_index: int,
	segment_count: int,
	prompt_source="motion",
	is_final=False,
	segment_start_frame=None,
	segment_effective_frames=None,
	fps=24,
):
	asset_versions = _reference_asset_versions_from_snapshot(shot, project)
	# Multi-reference prompts are written by the director planner, which already
	# folded the global instructions into each take. Appending the whole-film
	# brief again makes the model render every place in one take as a montage.
	# Segment timing is appended below after clipping it to this segment's time
	# window. Compiling the full motion prompt here would leak the entire shot's
	# action plan into every continuation.
	base_prompt_source = "creative" if prompt_source == "motion" and segment_count > 1 else prompt_source
	base = compile_prompt_for_documents(
		shot, project, include_global_instructions=not asset_versions,
		prompt_source=base_prompt_source, is_final=is_final,
	)
	if asset_versions:
		from .film_director import reference_preamble

		# Continuations receive the same reference images as the first segment.
		base = f"{reference_preamble(asset_versions, project.get('references') or [])}\n\n{base}"
	if segment_count == 1:
		return base
	start_seconds = None
	end_seconds = None
	if segment_start_frame is not None and segment_effective_frames is not None:
		try:
			fps = float(fps)
			if fps > 0:
				start_seconds = float(segment_start_frame) / fps
				end_seconds = start_seconds + float(segment_effective_frames) / fps
		except (TypeError, ValueError):
			pass
	timing = temporal_timing_instruction(
		shot, is_final=is_final, start_seconds=start_seconds, end_seconds=end_seconds
	)
	if segment_index == 1:
		return (
			f"{base}\n\nThis is segment 1 of {segment_count}. "
			"Begin the planned action naturally.\n\n"
			f"{timing}"
		).strip()
	return (
		f"{base}\n\nThis is continuation segment {segment_index} of {segment_count}. "
		"Continue seamlessly from the previous clip's exact last frame with the same motion, light and sound. "
		"Do not restart or reintroduce the action.\n\n"
		f"{timing}"
	).strip()


def compile_prompt_for_documents(shot, project, include_global_instructions=True, prompt_source="motion", is_final=False):
	prompt_source = prompt_source if prompt_source in PROMPT_SOURCES else "creative"
	# A keyframe stage needs the still composition while a video stage needs the
	# motion-aware scene. Either field can be absent on an older storyboard, so
	# retain a deterministic fallback without overwriting the stored prompts.
	if prompt_source == "image":
		prompt = (getattr(shot, "image_prompt", None) or getattr(shot, "generation_prompt", None) or "").strip()
	else:
		prompt = (getattr(shot, "generation_prompt", None) or getattr(shot, "image_prompt", None) or "").strip()
	if not prompt:
		frappe.throw(
			_("Shot {0} has no generation prompt.").format(shot.name)
		)

	global_instructions = str(project.get("global_instructions") or "").strip()
	if global_instructions and include_global_instructions:
		prompt = (
			f"{prompt}\n\n"
			"Global instructions that apply to every shot:\n"
			f"{global_instructions}"
		)

	if getattr(shot, "references", None):
		prompt = (
			f"{prompt}\n\n"
			"Reference fidelity: market only the intended referenced product. Preserve its exact "
			"shape, material, color, proportions, and every visible logo or label; do not swap, "
			"merge, deform, or invent products, packaging, text, or logos."
		)

	generation_mode = project.get("generation_mode")
	if prompt_source == "motion" and generation_mode in ("Continuous", "Consistency"):
		if int(shot.shot_number or 0) > 1:
			prompt = (
				f"{prompt}\n\n"
				"Continuity: Continue naturally from the previous shot's generated last frame. "
				"Preserve the product geometry, color, orientation, and scene state. "
				"Describe the next movement from the existing pose rather than reintroducing "
				"the product from scratch."
			)
	if prompt_source == "motion":
		timing = temporal_timing_instruction(shot, is_final=is_final)
		if timing:
			prompt = f"{prompt}\n\n{timing}"
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
		"image_prompt": getattr(shot, "image_prompt", None) or "",
		"motion_plan_json": getattr(shot, "motion_plan_json", None) or "",
		"start_state": getattr(shot, "start_state", None) or "",
		"end_state": getattr(shot, "end_state", None) or "",
		"handoff_type": getattr(shot, "handoff_type", None) or "",
		"global_instructions": project.get("global_instructions") or "",
	}
