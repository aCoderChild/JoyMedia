"""H3 serialization on top of JoyMedia's existing scene, timing and fidelity helpers.

Sources: MiniMaxAI/MiniMax-H3 docs/VIDEO_PROMPT_WRITING_GUIDE_{base,ref}_en.md.
Camera direction is chosen once from structure, independently of storyboard prose.
"""

import json
import re

from joymedia.services.planning.camera import camera_plan
from joymedia.services.planning.camera import without_camera as _without_camera


def compile_opening_hold(shot, workflow, composition):
	"""A preparation clip holds one opening state; it does not perform later actions."""
	definitions, retention, uses = _reference_sections(shot, workflow, True)
	return (
		"For the target video, at 0.00 seconds into the target video, the supplied reference pictures are fully referenced for [Shot 1].\n"
		+ definitions
		+ "\n"
		+ retention
		+ "\n\nintegrated_multimodal_description: [Shot 1] "
		+ uses
		+ " "
		+ composition
		+ " Hold exactly this opening pose, camera, props and composition throughout this preparation clip. "
		"Do not perform the later scripted action or change state. Reusable identity references do not replace "
		"authored scene props or contact. Keep the original anatomy, material, proportions and visible traits. "
		"Do not transfer packaging illustrations or branding onto loose materials unless explicitly authored. "
		"No new actor, duplicate subject, human hand or unauthored package."
		"\n\noverall_soundscape: N/A\n\nnon_diegetic_music: N/A"
	)


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
		_avoid,
		_identity_guard,
		_mood,
		_no_outsiders,
		first_frame_inventory,
		owned_body_parts,
		scene_actor,
		temporal_timing_instruction,
	)
	from joymedia.services.project.context import scene_direction
	from joymedia.services.project.formats import composition_instruction
	from joymedia.services.scene.contract import instruction
	from joymedia.services.scene.prompt_scope import (
		ACTOR_ROLES,
		assert_product_only_direction,
		product_only_instruction,
		sheet_material_instruction,
	)
	from joymedia.services.scene.prompt_scope import roles as reference_roles
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
	if (
		"product" in reference_roles(shot.get("references"))
		and not reference_roles(shot.get("references")) & ACTOR_ROLES
	):
		assert_product_only_direction(text)
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
	actor = scene_actor(shot, project)
	action = owned_body_parts(action, actor)
	physical = instruction(
		shot.get("motion_plan_json"),
		shot.get("duration_seconds"),
		start if segment_count > 1 else None,
		start + duration if segment_count > 1 else None,
		include_events=not bool(timing),
	)
	if segment_count > 1 and physical and not timing:
		action = ""
	# Lighting & Atmosphere carries only the look; what must never appear is a subject constraint.
	style = _mood(project, avoid=False) or (
		"Cinematic visual direction, preserving the established lighting and materials."
		if kind == "text"
		else "Keep the lighting, colour palette and mood established by the supplied frame."
	)
	never = _avoid(project)
	refs = "The supplied first frame controls identity, clothing, product geometry and artwork, environment, lighting and opening composition. Reference poses do not add actions."
	if kind == "text":
		refs = "Use only the subjects and environment described in this scene; no image or video references are supplied."
	if kind == "reference":
		# This graph receives the opening plus an optional product image, not
		# every Character/Environment row from the project library.
		refs = "<Picture 1> controls the opening composition, identity, environment and action state."
		roles = {str(r.get("reference_role") or "").lower() for r in shot.get("references") or []}
		if camera["product_focus"] or "product" in roles:
			refs += " <Picture 2> controls only exact product geometry, material and printed artwork; it depicts the same physical product, not another object or scene."
		if workflow and "product" in roles:
			# The roles the reference graph receives, inside Subject Identity rather than
			# appended after the five layers.
			refs += " Use <Picture 2> only for the exact advertised product silhouette, proportions, colours and printed artwork; keep its artwork attached to its surface through perspective, motion and occlusion."
		if workflow and roles & {"character", "person"}:
			refs += " Use the separate character reference only for the original character's face, markings, worn accessories, body proportions, limb and hand shape, and colours. A held heart or other object is a separate prop, never part of the character; include it only when the scene requests it. Retain the opening frame's pose and placement; do not add the reference image as a cutaway or duplicate actor."
	if reference_only:
		refs = _direct_reference_roles(shot, workflow)
	ref_definitions, ref_retention, ref_use = ("", "", "")
	if kind == "reference":
		ref_definitions, ref_retention, ref_use = _reference_sections(shot, workflow, reference_only)
		refs = ref_use
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
			"One coherent three-dimensional setting and shared light. Retain the referenced setting when supplied; ignore backgrounds in identity-only photos. No photo cards or split panels. Reference poses do not add props or actions."
		)
	else:
		guard = " ".join(part for part in (guard, _no_outsiders(shot, project)) if part)
	# Keep safety/continuity constraints, but one authoritative camera paragraph.
	rules = "\n\n".join(
		_without_camera(p) for p in text.split("\n\n")[1:] if not p.lstrip().startswith(("Audio:", "Camera:"))
	)
	rules = owned_body_parts(rules, actor)
	if shot.get("consistency_status") == "Redoing":
		note = str(shot.get("consistency_notes") or "").lower()
		if "human hand" in note or "outside hand" in note or "human arm" in note:
			rules += (
				" Retry correction: the previous take added a real human limb. Show only the declared character's own "
				"referenced paws; no bare human skin, human fingers, hand or arm may enter from any frame edge."
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
	if kind == "image":
		last = any(
			str(r.get("reference_role") or r.get("input_role") or "").lower() == "last_frame"
			for r in shot.get("references") or []
		)
		if last:
			ending += " Reach the final pose and composition established by Picture 2 at the end of the shot."
	# The five authoring concerns are not the model's wire format. H3's
	# official base guide requires an alignment line followed by three fields;
	# full-reference mode has six different fields. The local text encoder
	# forwards raw text and does not translate custom headings for us.
	visual = " ".join(
		p
		for p in [
			style,
			opening,
			refs,
			subject_identities(shot),
			guard,
			product_only_instruction(shot.get("references")),
			never,
			camera["direction"],
			composition_instruction(project),
			action,
			sheet_material_instruction(action),
			physical,
			rules,
			ending,
			*speech_parts,
		]
		if p
	)
	soundscape = sound or "Only sounds caused by the visible action."
	if sfx_only:
		visual += " No speech, no narration, no singing."
		soundscape += " No speech, no narration, no singing."
	if kind == "reference":
		return (
			f"subject_definitions:\n{ref_definitions}\n\n"
			+ f"summary: [{'reference generation' if reference_only else 'keyframe completion + reference generation'}] One continuous shot using only the supplied references in their declared roles.\n\n"
			+ f"retention_analysis:\n{ref_retention}\n\n"
			+ f"detailed_description: {style}\n[Shot 1] {visual.removeprefix(style).strip()}\n\n"
			+ f"overall_soundscape: {soundscape}\n\nnon_diegetic_music: {music}"
		)
	if kind == "image":
		if last:
			alignment = (
				"How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
				f"Picture 2 (from Shot 1) aligns with the {duration:.2f}-second mark of the target video."
			)
		else:
			alignment = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
	else:
		alignment = ""
	return (
		(alignment + "\n\n" if alignment else "")
		+ f"integrated_multimodal_description: [Shot 1] {visual}\n\n"
		+ f"overall_soundscape: {soundscape}\n\nnon_diegetic_music: {music}"
	)


def _reference_sections(shot, workflow, reference_only):
	"""Number only image references carried by the executable bindings."""
	descriptions = {
		"character": "the exact physical character identity, visible ear/eye design, proportions, colour and surface material",
		"person": "the exact person identity, clothing and visible anatomy",
		"product": "the single advertised product, its construction, proportions and original printed artwork; printed figures remain flat artwork",
		"environment": "the setting, furniture, supports and light, without introducing foreground actors",
		"general": "the authored material or detail reference, without introducing additional subjects",
	}
	definitions, retention, uses = [], [], []
	index = 0
	if not reference_only:
		index = 1
		definitions.append("<Picture 1> is the supplied opening frame of [Shot 1].")
		retention.append(
			"<Picture 1> ([Shot 1] first frame): fully_preserved - begin from its actual composition and state."
		)
		uses.append("The shot begins from <Picture 1>.")
	seen = set()
	subject = 0
	for binding in (workflow or {}).get("bindings") or []:
		role = str(binding.get("required_input_role") or "").lower()
		if role not in descriptions or role in seen:
			continue
		seen.add(role)
		for reference in shot.get("references") or []:
			if (
				not reference.get("asset_version")
				or str(reference.get("reference_role") or reference.get("input_role") or "").lower() != role
			):
				continue
			index += 1
			subject += 1
			label = f"<Subject {subject}>"
			definitions.append(f"{label} is {descriptions[role]}, supplied by <Picture {index}>.")
			retention.append(
				f"{label} (appears in [Shot 1]): fully_preserved - retain its declared {role} attributes; perform only the authored action."
			)
			uses.append(f"Use {label} for its declared {role} role.")
	return "\n".join(definitions), "\n".join(retention), " ".join(uses)


def subject_identities(shot):
	"""What each subject in the scene looks like, from its reference's stored analysis.

	Reference keys mean nothing to the video model; the analysed appearance of the
	approved picture (an immutable Asset Version) does.
	"""
	import frappe

	lines, seen = [], set()
	for row in shot.get("references") or []:
		role = str(row.get("reference_role") or "").lower()
		if role not in {"character", "person", "product"} or row.get("asset_version") in seen:
			continue
		seen.add(row.get("asset_version"))
		if "visual_description" in row:
			description = " ".join(str(row.get("visual_description") or "").split())
		else:
			# Compatibility for older snapshots only. New snapshots carry their
			# exact appearance text and never reinterpret a mutable caption.
			from joymedia.services.scene.prompt_scope import reference_description

			analysis = frappe.parse_json(
				frappe.db.get_value("Asset Version", row.get("asset_version"), "analysis_json") or "{}"
			)
			description = reference_description(analysis, role)
		description = re.sub(r"^Visible construction:[^.]*\.\s*", "", description)
		if role == "product":
			# Vision descriptions are useful for geometry, but OCR-like prose can invent
			# packaging copy. The original product image, not generated OCR, owns print.
			description = re.sub(
				r"(?i)(?:^|(?<=\.\s))(?:text|label|lettering|words|print(?:ed text)?)\s+(?:reads?|says?|shows?|states?|includes?)\b[^.]*\.?\s*",
				"",
				description,
			).strip()
		if description:
			lines.append(f"The {'product' if role == 'product' else 'character'}: {description}")
	return " ".join(lines)


def unheld_product(shot):
	"""A product-only scene: no actor exists to touch it, so no hand may appear."""
	roles = {str(r.get("reference_role") or "").lower() for r in shot.get("references") or []}
	if "product" in roles and not roles & {"character", "person"}:
		return "The product stands on its own: nothing and no one touches it; no hands, arms, paws or people enter the frame."
	return ""


LAYERS = ("Camera Direction", "Subject Identity", "Motion & Physics", "Lighting & Atmosphere", "Audio SFX")


def five_layers(camera, subject, motion, lighting, audio):
	"""Input-standards-H3: every H3 prompt is English, in five ordered layers:
	[Camera Direction] + [Subject Identity] + [Motion & Physics] + [Lighting & Atmosphere] + [Audio SFX].
	"""
	parts = (camera, subject, motion, lighting, audio)
	return "\n\n".join(
		f"{label}: "
		+ re.sub(r"\.(\s*\.)+", ".", " ".join(" ".join(str(p).split()) for p in part if str(p or "").strip()))
		for label, part in zip(LAYERS, parts, strict=True)
	)


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
		for ref in matches:
			statement = f"<Picture {len(statements) + 1}> controls {descriptions[role]}."
			if role == "product" and ref.get("visual_description"):
				statement += " Visible product construction and markings: " + str(ref["visual_description"])
			statements.append(statement)
	if not statements:
		raise ValueError("Reference-only video needs at least one declared image reference.")
	return " ".join(statements)
