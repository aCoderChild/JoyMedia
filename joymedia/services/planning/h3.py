"""H3 serialization on top of JoyMedia's existing scene, timing and fidelity helpers.

Sources: MiniMaxAI/MiniMax-H3 docs/VIDEO_PROMPT_WRITING_GUIDE_{base,ref}_en.md.
Camera direction is chosen once from structure, independently of storyboard prose.
"""

import json
import re

from joymedia.services.planning.camera import camera_plan
from joymedia.services.planning.camera import without_camera as _without_camera


def h3_kind(workflow):
	if not workflow:
		return None
	graph = workflow.get("workflow_json") or {}
	if isinstance(graph, str):
		graph = json.loads(graph)
	classes = {n.get("class_type") for n in graph.values() if isinstance(n, dict)}
	if "MiniMaxH3ReferenceToVideo" in classes:
		return "reference"
	if "MiniMaxH3ImageToVideo" in classes:
		return "image"
	if "MiniMaxH3TextToVideo" in classes:
		return "text"
	return None


def compile_h3(
	shot,
	project,
	kind="image",
	segment_index=1,
	segment_count=1,
	is_final=False,
	segment_start_frame=None,
	segment_effective_frames=None,
	fps=24,
	workflow=None,
):
	from joymedia.services.planning.framing import inspect_framing
	from joymedia.services.planning.prompts import (
		_audio_line_last,
		_identity_guard,
		_mood,
		first_frame_inventory,
		temporal_timing_instruction,
	)
	from joymedia.services.project.context import scene_direction
	from joymedia.services.scene.contract import instruction
	from joymedia.services.workflows.capabilities import controls

	reference_only = bool(workflow and "reference_only" in controls(workflow))

	# A continuation starts at a generated upstream last frame, not the
	# authored first-frame reference; its old bounds cannot authorize a move.
	framing = (
		inspect_framing(shot)
		if not reference_only
		and kind != "text"
		and segment_index == 1
		and shot.get("continuity_mode") != "Continue"
		else None
	)
	camera = camera_plan(
		shot, project, is_final=is_final, framing_safety=framing, generated_composition=reference_only
	)
	text = str(shot.get("generation_prompt") or shot.get("image_prompt") or "").strip()
	if not text:
		raise ValueError("The scene needs an action prompt.")
	# Accept an authored H3 field block without nesting another set of fields.
	fields = dict(
		re.findall(
			r"(?ms)^(integrated_multimodal_description|overall_soundscape|non_diegetic_music):\s*(.*?)(?=^(?:integrated_multimodal_description|overall_soundscape|non_diegetic_music):|\Z)",
			text,
		)
	)
	if fields.get("integrated_multimodal_description"):
		visual = re.sub(r"^\s*\[Shot 1\]\s*", "", fields["integrated_multimodal_description"]).strip()
		if re.search(r"\[Shot [2-9]\d*\]", visual):
			raise ValueError("Use a separate storyboard scene for each continuous shot.")
		score = fields.get("non_diegetic_music", "").strip()
		text = visual + "\n\nAudio: " + fields.get("overall_soundscape", "").strip()
		if score and score != "N/A":
			text += "; music: " + score
	start = float(segment_start_frame or 0) / float(fps)
	duration = (
		float(segment_effective_frames) / float(fps)
		if segment_effective_frames
		else float(shot.get("duration_seconds") or 5)
	)
	window = {"start_seconds": start, "end_seconds": start + duration} if segment_count > 1 else {}
	timing = temporal_timing_instruction(shot, is_final=is_final, **window)
	# A continuation gets only its window of the action plan, never the full beat again.
	action = _without_camera(timing or scene_direction(text)["action"])
	physical = instruction(
		shot.get("motion_plan_json"),
		shot.get("duration_seconds"),
		start if segment_count > 1 else None,
		start + duration if segment_count > 1 else None,
		include_events=not bool(timing),
	)
	if segment_count > 1 and physical and not timing:
		action = ""
	style = _mood(project) or (
		"Cinematic visual direction, preserving the established lighting and materials."
		if kind == "text"
		else "Use the visual style, lighting, materials and mood established by the supplied frame."
	)
	refs = "The supplied first frame controls identity, clothing, product geometry and artwork, environment, lighting and opening composition. Reference poses do not add actions."
	if kind == "text":
		refs = "Use only the subjects and environment described in this scene; no image or video references are supplied."
	if kind == "reference":
		# This graph receives the opening plus an optional product image, not
		# every Character/Environment row from the project library.
		refs = "<Picture 1> controls the opening composition, identity, environment and action state."
		if camera["product_focus"]:
			refs += " <Picture 2> controls only exact product geometry, material and printed artwork; it depicts the same physical product, not another object or scene."
	if reference_only:
		refs = _direct_reference_roles(shot, workflow)
	opening = (
		"Continue from the preceding segment's exact last frame without restarting the action."
		if segment_index > 1
		else "Begin with the supplied opening frame, preserving its existing framing and visible subjects. "
		+ str(shot.get("start_state") or "")
	)
	if kind == "text":
		opening = f"Begin with a {camera['framing']}. " + str(shot.get("start_state") or "")
	elif reference_only:
		opening = f"Generate a {camera['framing']} opening. " + str(shot.get("start_state") or "")
		opening += " The references supply their declared identities and setting, not a fixed opening frame. Compose this authored view rather than copying full-body reference framing or photo backgrounds."
	elif shot.get("references"):
		inventory = first_frame_inventory(shot, project)
		if inventory:
			opening += " Visible subjects: " + inventory + "."
	opening += " One continuous shot with no cuts."
	guard = (
		_identity_guard(shot, project, include_camera=False, include_style=False, concise=True)
		if shot.get("references")
		else ""
	)
	if reference_only:
		guard = (
			"Only the declared physical subjects appear. Alternate pictures are views of the same identity, not extra subjects. "
			"Packaging illustrations are flat printed artwork, never separate actors. Every visible limb belongs to the declared actor and retains its anatomy; no unrequested human hands. "
			"One coherent three-dimensional setting and shared light; no photo cards, split panels or imported reference backgrounds. Reference poses do not add props or actions."
		)
	# Keep safety/continuity constraints, but one authoritative camera paragraph.
	rules = "\n\n".join(
		_without_camera(p) for p in text.split("\n\n")[1:] if not p.lstrip().startswith(("Audio:", "Camera:"))
	)
	sfx_only = (project.get("soundtrack_mode") or "Sound effects only") != "Full soundtrack"
	audio = _audio_line_last(text, sound_effects_only=sfx_only, duration=duration)
	audio = next((p[6:].strip() for p in audio.split("\n\n") if p.startswith("Audio:")), "")
	# Split only labelled audio channels, not punctuation inside exact dialogue.
	channels = re.split(
		r";\s*(?=(?:music|dialogue|speech|narration|voiceover|sound effects|SFX)\s*:)", audio, flags=re.I
	)
	music_parts, speech_parts, sound_parts = [], [], []
	for channel in channels:
		label, sep, value = channel.partition(":")
		if sep and label.strip().lower() == "music":
			music_parts.append(value.strip())
		elif sep and label.strip().lower() in {"dialogue", "speech", "narration", "voiceover"}:
			if not sfx_only:
				speech_parts.append(value.strip())
		elif channel.strip():
			sound_parts.append(channel.strip())
	sound = "; ".join(sound_parts)
	music = "N/A" if sfx_only or not music_parts else "; ".join(music_parts)
	ending = (
		"End with "
		+ str(shot.get("end_state") or "the resolved action and a stable, unobstructed composition").rstrip(
			". "
		)
		+ "."
	)
	if camera["closing"]:
		ending += " Settle into a stable final hold; CTA lettering is added by the editor."
	body = "\n\n".join(
		p
		for p in [
			style,
			refs,
			opening,
			action,
			physical,
			rules,
			guard,
			camera["direction"],
			" ".join(speech_parts),
			ending,
		]
		if p
	)
	if kind == "reference":
		return f"subject_definitions: {refs}\n\nsummary: One continuous shot.\n\nretention_analysis: Preserve the declared reference identities and product artwork.\n\ndetailed_description: [Shot 1] {body}\n\noverall_soundscape: {sound or 'Only sounds caused by the visible action; no invented speech.'}\n\nnon_diegetic_music: {music}"
	anchor = ""
	if kind == "image":
		last = any(
			str(r.get("reference_role") or r.get("input_role") or "").lower() == "last_frame"
			for r in shot.get("references") or []
		)
		if last:
			anchor = f"How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the {duration:.2f}-second mark of the target video.\n\n"
			body += (
				"\n\nReach the final pose and composition established by Picture 2 at the end of the shot."
			)
		else:
			anchor = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
	return f"{anchor}integrated_multimodal_description: [Shot 1] {body}\n\noverall_soundscape: {sound or 'Only sounds caused by the visible action; no invented speech.'}\n\nnon_diegetic_music: {music}"


def _direct_reference_roles(shot, workflow):
	"""Native R2V image ordinals follow present bindings, never library order."""
	descriptions = {
		"character": "only the actor identity, anatomy and material; ignore its photo background and incidental pose",
		"person": "only the person identity, clothing and visible anatomy; ignore the photo background and incidental props",
		"product": "the same single advertised product, its silhouette, proportions, material, colours and printed artwork; printed characters stay flat on the package",
		"environment": "only the fixed setting, support surfaces, light and depth; ignore incidental foreground subjects",
		"general": "the authored material structure and surface detail, not additional physical subjects",
	}
	roles, statements = set(), []
	for binding in workflow.get("bindings") or []:
		role = str(binding.get("required_input_role") or "").lower()
		if role in roles or role not in descriptions:
			continue
		roles.add(role)
		matches = [
			r
			for r in shot.get("references") or []
			if str(r.get("reference_role") or r.get("input_role") or "").lower() == role
		]
		for _ref in matches:
			statements.append(f"<Picture {len(statements) + 1}> controls {descriptions[role]}.")
	if not statements:
		raise ValueError("Reference-only video needs at least one declared image reference.")
	return " ".join(statements)
