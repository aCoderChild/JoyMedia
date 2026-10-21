"""Compiles the prompt a workflow receives for a scene: the scene's own text for the stage (image or motion), the
rules that keep characters, products and places as in the first frame, the action timing of each segment and the
scene's sound line. Also the keyframe prompt for drawing characters or leaving a setting empty for pasted art.
"""

import hashlib
import json
import re

import frappe
from frappe import _

from joymedia.services.scene.contract import instruction as physical_instruction

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
	ending = (
		"Conclude the whole film in the stated end state; settle and hold the final composition. Do not prepare another shot, transition, or new action."
		if is_final or handoff == "ending"
		else (
			(f"Finish in this state: {end_state}. " if end_state else "")
			+ "Keep this same continuous scene through the end of the clip. Do not cut, transition or begin another shot; the editor handles the next shot."
		)
	)
	return "Chronological action plan (approximate timing): " + "; ".join(parts) + ". " + ending


def compile_prompt(shot: str):
	shot = frappe.get_doc("Shot", shot)
	project = frappe.get_doc("Media Project", shot.media_project)
	return compile_prompt_for_documents(shot, project)


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
	workflow=None,
):
	if prompt_source == "motion":
		from joymedia.services.planning.h3 import compile_h3, h3_kind

		kind = h3_kind(workflow)
		if kind:
			return compile_h3(
				shot,
				project,
				kind=kind,
				segment_index=segment_index,
				segment_count=segment_count,
				is_final=is_final,
				segment_start_frame=segment_start_frame,
				segment_effective_frames=segment_effective_frames,
				fps=fps,
				workflow=workflow,
			)
	asset_versions = _reference_asset_versions_from_snapshot(shot, project)
	# Multi-reference prompts are written by the director planner, which already
	# folded the global instructions into each take. Appending the whole-film
	# brief again makes the model render every place in one take as a montage.
	# Segment timing is appended below after clipping it to this segment's time
	# window. Compiling the full motion prompt here would leak the entire shot's
	# action plan into every continuation.
	base_prompt_source = "creative" if prompt_source == "motion" and segment_count > 1 else prompt_source
	base = compile_prompt_for_documents(
		shot,
		project,
		include_global_instructions=not asset_versions,
		prompt_source=base_prompt_source,
		is_final=is_final,
	)
	if prompt_source == "image":
		base += _ordered_image_reference_roles(shot, workflow)

	def finish(text):
		from joymedia.services.planning.shot_structure import structure_for

		plan = shot.get("motion_plan_json") or {}
		if isinstance(plan, str):
			plan = json.loads(plan)
		if prompt_source == "motion" and (structure_for(shot) or plan.get("camera_intent")):
			from joymedia.services.planning.camera import camera_plan, without_camera
			from joymedia.services.planning.framing import inspect_framing
			from joymedia.services.workflows.capabilities import controls

			generated = bool(workflow and "reference_only" in controls(workflow))
			framing = (
				inspect_framing(shot)
				if not generated and segment_index == 1 and shot.get("continuity_mode") != "Continue"
				else None
			)
			direction = camera_plan(
				shot, project, is_final=is_final, framing_safety=framing, generated_composition=generated
			)
			text = without_camera(text) + "\n\n" + direction["direction"]
			text = _audio_line_last(
				text,
				sound_effects_only=(project.get("soundtrack_mode") or "Sound effects only")
				!= "Full soundtrack",
				duration=float(segment_effective_frames) / float(fps)
				if segment_effective_frames
				else float(shot.get("duration_seconds") or 5),
			)
		# Continuation segments are written from the creative text, so they need the cast and audio rules too.
		if prompt_source != "motion" or segment_count == 1:
			return text
		if shot.get("references") if hasattr(shot, "get") else getattr(shot, "references", None):
			text = f"{text}\n\n{_identity_guard(shot, project, include_camera=not (structure_for(shot) or plan.get('camera_intent')))}"
		return _audio_line_last(
			text,
			sound_effects_only=(project.get("soundtrack_mode") or "Sound effects only") != "Full soundtrack",
			duration=(float(segment_effective_frames) / float(fps))
			if segment_effective_frames and fps
			else 5.0,
		)

	if asset_versions:
		from joymedia.services.planning.film_director import reference_preamble

		# Continuations receive the same reference images as the first segment.
		base = f"{reference_preamble(asset_versions, project.get('references') or [])}\n\n{base}"
	if segment_count == 1 or prompt_source == "image":
		# A still image has no segments or timing; the action plan belongs to the video stage.
		return finish(base)
	has_references = bool(
		shot.get("references") if hasattr(shot, "get") else getattr(shot, "references", None)
	)
	if prompt_source == "motion" and has_references:
		base = _scrub_paragraphs(base, **_scrub_options(shot, project))
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
	physical = (
		physical_instruction(
			getattr(shot, "motion_plan_json", None),
			getattr(shot, "duration_seconds", None),
			start_seconds,
			end_seconds,
		)
		if prompt_source == "motion"
		else ""
	)
	if physical:
		timing = f"{timing}\n\n{physical}"
	if prompt_source == "motion" and has_references:
		# The action plan is written from the beat's own text, so it needs the same treatment.
		timing = _scrub_printable(timing, **_scrub_options(shot, project))
	if segment_index == 1:
		return finish(
			(
				f"{base}\n\nThis is segment 1 of {segment_count}. "
				"Begin the planned action naturally.\n\n"
				f"{timing}"
			).strip()
		)
	return finish(
		(
			f"{base}\n\nThis is continuation segment {segment_index} of {segment_count}. "
			"Continue seamlessly from the previous clip's exact last frame with the same motion, light and sound. "
			"Do not restart or reintroduce the action.\n\n"
			f"{timing}"
		).strip()
	)


def compile_prompt_for_documents(
	shot, project, include_global_instructions=True, prompt_source="motion", is_final=False
):
	prompt_source = prompt_source if prompt_source in PROMPT_SOURCES else "creative"
	# A keyframe stage needs the still composition while a video stage needs the
	# motion-aware scene. Either field can be absent on an older storyboard, so
	# retain a deterministic fallback without overwriting the stored prompts.
	if prompt_source == "image":
		prompt = (
			getattr(shot, "image_prompt", None) or getattr(shot, "generation_prompt", None) or ""
		).strip()
	else:
		prompt = (
			getattr(shot, "generation_prompt", None) or getattr(shot, "image_prompt", None) or ""
		).strip()
	if not prompt:
		frappe.throw(_("Shot {0} has no generation prompt.").format(shot.name))

	if prompt_source == "motion" and getattr(shot, "references", None):
		actor = scene_actor(shot, project)
		prompt = "\n\n".join(
			owned_body_parts(_scrub_printable(part, **_scrub_options(shot, project)), actor)
			if not part.lstrip().startswith("Audio:")
			else part
			for part in prompt.split("\n\n")
		)
	if prompt_source == "image":
		from joymedia.services.keyframes.overlay import (
			DRAW,
			EMPTY_SETTING,
			PASTE,
			pasted_references,
			usable_setting,
		)

		mode = getattr(shot, "character_mode", None) or PASTE
		references = getattr(shot, "references", None) or []
		if mode == DRAW and any(_role_of(r) in ("character", "person") for r in references):
			return _with_opening_staging(_draw_prompt(shot, project), shot) + _image_reference_roles(
				references
			)
		if pasted_references(references, mode):
			# The real characters and products are pasted in afterwards, so the image model gets the place only.
			# Anything else in the prompt (names, actions, fidelity rules) would be drawn into it.
			return f"{usable_setting(getattr(shot, 'setting_prompt', None))}\n\n{EMPTY_SETTING}"

	if prompt_source == "image":
		prompt = _with_opening_staging(prompt, shot) + _image_reference_roles(
			getattr(shot, "references", None) or []
		)

	global_instructions = str(project.get("global_instructions") or "").strip()
	if global_instructions and include_global_instructions:
		prompt = f"{prompt}\n\nGlobal instructions that apply to every shot:\n{global_instructions}"

	if getattr(shot, "references", None):
		prompt = (
			f"{prompt}\n\n"
			"Reference fidelity: show only the intended reference subjects and assets. Keep their exact shape, material, "
			"colours, proportions, artwork and marks; do not swap, merge, deform or invent subjects, products or "
			"logos. Preserve the reference's existing print detail and legibility. Do not translate, retype, blur or replace its artwork; add no new markings."
		)

	generation_mode = project.get("generation_mode")
	continuity = getattr(shot, "continuity_mode", None)
	continue_scene = continuity == "Continue" or (
		not continuity and generation_mode in ("Continuous", "Consistency")
	)
	if prompt_source == "motion" and continue_scene:
		if int(shot.shot_number or 0) > 1:
			prompt = (
				f"{prompt}\n\n"
				"Continuity: Continue naturally from the previous shot's generated last frame. "
				"Preserve the product geometry, color, orientation, and scene state. "
				"Describe the next movement from the existing pose rather than reintroducing "
				"the product from scratch."
			)
	if prompt_source == "motion" and getattr(shot, "references", None):
		from joymedia.services.planning.shot_structure import structure_for

		plan = shot.get("motion_plan_json") or {}
		if isinstance(plan, str):
			plan = json.loads(plan)
		prompt = f"{prompt}\n\n{_identity_guard(shot, project, include_camera=not (structure_for(shot) or plan.get('camera_intent')))}"
	if prompt_source == "motion":
		timing = temporal_timing_instruction(shot, is_final=is_final)
		if timing:
			prompt = f"{prompt}\n\n{timing}"
		physical = physical_instruction(
			getattr(shot, "motion_plan_json", None), getattr(shot, "duration_seconds", None)
		)
		if physical:
			prompt = f"{prompt}\n\n{physical}"
		prompt = _audio_line_last(
			prompt,
			sound_effects_only=(project.get("soundtrack_mode") or "Sound effects only") != "Full soundtrack",
			duration=float(getattr(shot, "duration_seconds", None) or 5.0),
		)
	return prompt.strip()


def _identity_guard(shot, project, include_camera=True, include_style=True, concise=False):
	"""The cast, colour and no-extras rules every video segment of a scene with references must carry.

	The video model keeps no identity of its own beyond the supplied frame and tends to redesign a character the
	moment the camera moves in close, or to invent another one for any animal, person or product the text names.
	State the cast once, then resolve every name and body part against it.
	"""
	if concise:
		rules = keep_rules(shot, project)
		return (
			"Preserve the supplied subjects' identity, anatomy, proportions, colours and materials. "
			"No extra physical subjects; pictures printed on a surface remain flat artwork. "
			"Preserve existing printed quantities, names and artwork; add no new markings. "
			+ (f"Reference constraints: {rules}." if rules else "")
		)
	names = _character_names(shot, project)
	inventory = first_frame_inventory(shot, project)
	if len(names) > 1:
		who = (
			f"The only characters in this scene are {' and '.join(names)}. They are different individuals: never "
			"merge them, swap them, or draw one of them twice. "
			f"{_kinship_hint(names)}Every visible limb belongs to its own character. No additional character appears. "
		)
	elif names:
		who = (
			f"The only character in this scene is {names[0]}. Every character or person named in this prompt is this "
			"one, and every visible limb belongs to it, never a separate person. No additional character appears. "
		)
	else:
		who = (
			"Every named subject in this prompt is one of the subjects shown in the supplied first frame; no "
			"additional subject appears. "
		)
	return (
		(
			f"The first frame contains exactly: {inventory}. Nothing else is added: no unreferenced subject or duplicate "
			"asset. Whatever the text says anyone does, the listed subjects do it. "
			if inventory
			else ""
		)
		+ _closing_shot_rule(shot, project)
		+ _split_screen_rule(shot)
		+ (f"Must stay as is: {keep_rules(shot, project)}. " if keep_rules(shot, project) else "")
		+ (_mood(project) if include_style else "")
		+ "Scene fidelity: the supplied first frame is the truth for the place, the lighting, the time of day, the "
		"characters and every object. Keep them for the whole clip; this text describes only what moves, and any "
		"description of a different place, lighting or object in it is ignored. "
		+ (
			# A split screen's panels hold still; the sheet's own camera move wins elsewhere, and the pack is then held
			# exactly only while it stays in place.
			""
			if not include_camera or _views(shot)
			else "The camera stays completely still: no zoom, pan or push-in. "
			if _camera_locked(shot)
			else "Follow the camera direction given above. "
			if camera_moves(shot)
			else "The camera stays completely still: no zoom, pan or push-in. "
			if holds_product(shot)
			else "The camera stays completely still: no zoom, pan or push-in. The advertised product stays at its authored support and position "
			"for the whole clip; nobody picks it up and nothing passes in front of it. "
			if _locked_product(shot)
			else "Keep the camera framing of the first frame: allow at most a very slight, slow push-in, so that every character "
			"and product stays in view and unchanged. "
		)
		+ (
			"The depicted holder keeps contact with the same advertised product for the whole clip; its shape and surface stay unchanged, with its "
			"front to the viewer. "
			if holds_product(shot)
			else ""
		)
		+ "Preserve existing printed quantities, names and artwork; add no new markings. "
		+ product_identity(
			project, shows=any(_role_of(r) == "product" for r in getattr(shot, "references", None) or [])
		)
		+ f"Identity consistency: {who}Every product is the approved product asset shown in the first frame; never add "
		"a duplicate or substitute. Add no new lettering, captions or invented logos; existing asset markings "
		"stay as they are. Keep every referenced subject and asset exactly as shown—same geometry, colours, material, "
		"face, proportions and visible details—in every camera angle, including close-ups; never redesign or recolour it."
	)


def _ordered_image_reference_roles(shot, workflow):
	"""Name pictures in the order declared by a multi-reference workflow's chains."""
	if not workflow:
		return ""
	spec = workflow.get("execution_spec") or {}
	if isinstance(spec, str):
		spec = json.loads(spec)
	if "multi_reference" not in (spec.get("capabilities") or []):
		return ""
	refs = getattr(shot, "references", None) or []
	pictures = []
	bindings = workflow.get("bindings")
	declared = (
		{str(row.get("required_input_role") or "").lower() for row in bindings or []}
		if bindings is not None
		else None
	)
	seen = set()
	for chain in (spec.get("input_preprocessing") or {}).get("optional_input_chains") or []:
		for link in chain.get("links") or []:
			role, slot = str(link.get("role") or "").lower(), int(link.get("slot") or 0)
			if declared is not None and role not in declared:
				continue
			matches = [row for row in refs if _role_of(row) == role]
			if slot >= len(matches) or (role, slot) in seen:
				continue
			seen.add((role, slot))
			control = {
				"person": "only the actor's visible anatomy and identity; ignore incidental products and their pose",
				"character": "only the character's identity and anatomy",
				"product": "the actual advertised product, its complete design and material; use the authored opening pose",
				"environment": "only the support surface, location and light; ignore incidental foreground props",
			}.get(role)
			if control:
				pictures.append(f"Image {len(pictures) + 1} controls {control}.")
	return "\n\nPicture assignments: " + " ".join(pictures) if pictures else ""


def _image_reference_roles(references):
	"""Separate ownership when source photos contain incidental actors or objects."""
	roles = {_role_of(row) for row in references}
	if len(roles) < 2:
		return ""
	parts = []
	if "product" in roles:
		parts.append(
			"Product references control the advertised object's geometry, complete visible artwork and material in the authored pose. Characters depicted on packaging remain flat printed artwork, never additional physical actors. Products incidentally visible in other reference roles must not override this design or introduce a different fold or crop."
		)
	if roles & {"person", "character"}:
		parts.append(
			"Person and Character references control the corresponding actor's identity and visible anatomy; use the authored opening pose, rather than copying their incidental props or actions."
		)
	if "environment" in roles:
		parts.append(
			"Environment references control the setting, support texture and lighting only; do not copy their incidental foreground objects or replace the advertised product with them."
		)
	return "\n\nReference roles: " + " ".join(parts) if parts else ""


def _views(shot):
	from joymedia.services.keyframes.locations import shot_views

	return shot_views(
		shot if hasattr(shot, "get") else frappe._dict(views_json=getattr(shot, "views_json", None))
	)


def _split_screen_rule(shot):
	"""A split screen is one first frame of stacked panels: the video keeps them apart and in place."""
	views = _views(shot)
	if not views:
		return ""
	return (
		f"This is a split screen: {len(views)} panels stacked top to bottom, separated by thin white lines. The panels and "
		"the lines stay exactly where they are for the whole clip, each panel keeps its own place, nothing moves from one "
		"panel into another, and the camera does not move. Inside each panel only gentle, natural movement. "
	)


def _closing_shot_rule(shot, project):
	"""On the advertisement's last scene the product, not a supporting subject, holds attention."""
	from joymedia.services.keyframes.overlay import closes_film

	if not any(_role_of(r) == "product" for r in getattr(shot, "references", None) or []) or not closes_film(
		shot, project
	):
		return ""
	return (
		"This is the closing shot: the product in the centre is the hero. It stays still, upright, sharp and fully "
		"visible in the centre for the whole clip; the characters stay at the two sides, gesture toward it and never "
		"cover it. The background stays as in the first frame: no title, end card, banner, sign or floating logo appears. "
	)


NO_VOICE_OR_MUSIC = (
	"Sound effects only: no speech, no dialogue, no narration, no singing, no laughing or other vocal sounds, "
	"no background music."
)
VOCAL_SOUND = re.compile(
	r"\b(laugh\w*|giggl\w*|voice\w*|speak\w*|speech|talk\w*|sing\w*|song|cry\w*|scream\w*|shout\w*|whisper\w*|say\w*|hum\w*|gasp\w*)\b",
	re.I,
)


def _kinship_hint(names):
	"""Resolve family words to the intended cast member when several roles are present."""
	from joymedia.services.planning.roles import role_words

	roles = [(name, role_words(name)) for name in dict.fromkeys(n.split(" (")[0] for n in names)]
	roles = [(name, words) for name, words in roles if words]
	if len(roles) < 2:
		return ""
	return "In the text, " + "; ".join(f"a {', '.join(words[:5])} is {name}" for name, words in roles) + ". "


PRINTABLE = re.compile(
	r"\(\s*\d[^)]*\)|\b\d+\s*(?:packs?|boxes|box|sheets?|ply|layers?|rolls?|pcs|pieces)\b|[\"“”][^\"“”]*[\"“”]|(?<![\w])'[^'\n]{2,}'(?!\w)"
	# Where things stand is fixed by the first frame; a placement in the text makes the model draw a second copy.
	r"|\b(?:at|in|on|to|from)\s+(?:the\s+)?(?:(?:top|bottom|upper|lower)[ -]*)?(?:left|right|centre|center)"
	r"(?:[ -]*(?:hand\s+)?(?:corner|side|of the (?:frame|screen)))?(?:\s+of the (?:frame|screen))?",
	re.I,
)


PACKAGING = re.compile(
	r"\b(?:(?:large|big|huge|giant|bulk)\s+)?(boxes|box|cartons?|cases?|crates?)\b|\bbulk packaging\b", re.I
)
CAMERA_ZOOM = re.compile(r"[^.!?]*\b(?:zoom\w*|push(?:es|ing)?[ -]in|dolly\w* in)\b[^.!?]*[.!?]?", re.I)


def _scrub_printable(text, packaging=True, zoom=True):
	"""Make movement text safe for a first frame: no printed quantities or quoted words, no placement, no extras.

	The video model prints whatever words it is given onto objects and draws a second copy of anything placed
	somewhere new. `packaging` turns a box or carton the text names into the product packs in the frame (the model
	invents one otherwise); `zoom` removes zoom sentences (a zoom enlarges pasted products until their printing is
	redrawn). Both are decided per scene by `_scrub_options`.
	"""
	text = SIMILE.sub("", PRINTABLE.sub("", without_overlay_text(text)))
	text = TEXTURE_WORDS.sub("", text)
	if packaging:
		text = PACKAGING.sub(
			lambda m: "product packs" if (m.group(1) or "").lower() in ("boxes",) else "product pack", text
		)
	if zoom:
		text = CAMERA_ZOOM.sub("", text)
	text = re.sub(r"\s{2,}", " ", text)
	return re.sub(r"\s+([.,;:!?])", r"\1", text).strip()


# Similes and texture words describe how something looks, and the video model takes them literally ("as if leaning
# into cloud-soft fur" grows fur on a smooth mascot). The first frame already shows how everything looks.
SIMILE = re.compile(
	r"[,;]?\s*\b(?:as if|as though|as (?:a|an|the)\b|like (?:a|an|the)\b|resembling)\b[^.;!?]*", re.I
)
TEXTURE_WORDS = re.compile(
	r"\b(?:fluffy|furry|fuzzy|cloud[- ]?like|cloud[- ]?soft|woolly|velvety|silky|plush)\b[ -]*", re.I
)


def _scrub_options(shot, project):
	"""Which of the optional scrub rules suit this scene.

	Object nouns are never reinterpreted as packaging. Camera zooms are constrained only when
	a source-art product layer is explicitly held in the frame.
	"""
	from joymedia.services.keyframes.overlay import pasted_references

	references = (shot.get("references") if hasattr(shot, "get") else getattr(shot, "references", None)) or []
	pasted_product = any(p["role"] == "product" for p in pasted_references(references, "Paste exact art"))
	return {"packaging": False, "zoom": pasted_product}


def _scrub_paragraphs(text, **options):
	"""Scrub the movement paragraphs of a prompt; the audio line is left as it is."""
	return "\n\n".join(
		part if part.lstrip().startswith("Audio:") else _scrub_printable(part, **options)
		for part in str(text).split("\n\n")
	)


def _display_name(label, number=1, total=1, person=False):
	"""A plain English name for a character: its family role when the label gives one, else the ASCII label, else
	"the mascot" ("the person" for a real person's photo), numbered only when the film has several."""
	from joymedia.services.planning.roles import role_name

	role = role_name(label)
	if role:
		return f"the {role} character"
	base = label.split(" (")[0].strip()
	if base.isascii() and base:
		return base
	kind = "person" if person else "mascot"
	return f"the {kind}" if total <= 1 else f"{kind} {number}"


def _same_character(first, second):
	"""Whether two cast names are one character: an alternate pose shares the same declared character identity."""
	first, second = (" ".join(str(name).split(" (")[0].casefold().split()) for name in (first, second))
	return first == second or first.startswith(second + " ") or second.startswith(first + " ")


def cast_number(label, labels):
	"""(number, total) of the character a label shows among the cast's labels; a pose counts with its character."""
	groups = []
	for other in labels:
		if other and not any(_same_character(other, group) for group in groups):
			groups.append(other)
	number = next(
		(index for index, group in enumerate(groups, 1) if _same_character(label, group)), len(groups) + 1
	)
	return number, max(len(groups), number)


def cast_name(label, project, person=False):
	"""The plain English name of a cast member of the project (see _display_name and cast_number)."""

	def field(row, key):
		return row.get(key) if hasattr(row, "get") else getattr(row, key, None)

	labels = [
		field(row, "label")
		for row in (project.get("references") or project.get("selected_media") or [])
		if frappe.scrub(field(row, "reference_role") or "") in ("character", "person", "people", "talent")
	]
	number, total = cast_number(label, labels)
	return _display_name(label, number, total, person)


def first_frame_inventory(shot, project):
	"""What the approved first frame contains, from the scene's references: characters left to right, then products."""

	def field(row, key):
		return row.get(key) if hasattr(row, "get") else getattr(row, key, None)

	references = getattr(shot, "references", None) or []
	if not any(_role_of(r) in ("character", "person", "product") for r in references):
		return ""
	names = [n.split(" (")[0] for n in _character_names(shot, project)]
	products = sum(1 for r in references if _role_of(r) == "product")
	ordered = (getattr(shot, "character_mode", None) or "Paste exact art") != "Draw in scene"
	parts = []
	if names:
		parts.append(f"{'from left to right ' if len(names) > 1 and ordered else ''}{' and '.join(names)}")
	if products:
		from joymedia.services.keyframes.overlay import closes_film

		views = _views(shot)
		if views:
			parts.append(
				f"in each of the {len(views)} stacked panels, the approved product asset{'s' if products > 1 else ''} in its middle"
			)
		elif closes_film(shot, project):
			parts.append(f"the approved product asset{'s' if products > 1 else ''}, large, in the centre")
		else:
			parts.append(
				f"{'beside them ' if names else ''}{products} approved product asset{'s' if products > 1 else ''}"
			)
	return ", ".join(parts)


def _role_of(reference):
	"""A reference's role for naming and counting: a real person counts as a character in a scene."""
	role = frappe.scrub(
		(
			reference.get("reference_role")
			if hasattr(reference, "get")
			else getattr(reference, "reference_role", "")
		)
		or ""
	)
	return "character" if role in ("person", "people", "talent") else role


def _describe_character(label, project=None):
	"""What the image model is told about a character: the label's detail (the References sheet's description),
	translated when it is not English, else its role."""
	detail = label.split(" (", 1)[1].rstrip(")") if " (" in label else ""
	if detail and detail.isascii():
		return detail
	if detail and project is not None:
		# A description in the sheet's language (the References sheet): translated, after the character's plain name.
		english = _english(detail, project).strip(" .")
		if english.isascii():
			return f"{cast_name(label, project)}: {english}"
	return cast_name(label, project) if project is not None else _display_name(label)


EXTREME_CLOSEUP = re.compile(
	r"\b(?:macro|extreme|super)(?:[ -]+(?:macro|extreme|super))*[ -]+close[ -]?ups?\b|\bmacro\b", re.I
)
QUANTITY = re.compile(
	r"\(\s*\d[^)]*\)|\b\d+\s*(?:packs?|boxes|box|sheets?|ply|layers?|rolls?|pcs|pieces)\b(?:\s+of)?|[\"“”][^\"“”]*[\"“”]|(?<![\w])'[^'\n]{2,}'(?!\w)",
	re.I,
)

# Words, logos and calls to action are laid over the finished film (services/editing/export.py); a picture or video model
# told to "display the logo" paints garbled letters, so these directions never reach it.
OVERLAY_DIRECTIVE = re.compile(
	r"[^.!?;\n]*\b(?:display|displays|displaying|show|shows|showing|add|adds|insert|overlay|write|writes|print|prints|put|include)\b"
	r"[^.!?;\n]*\b(?:logos?|captions?|slogans?|taglines?|call[- ]to[- ]action|cta|invitations?|on-screen text|text overlays?|messages?)\b[^.!?;\n]*[.!?;]?\s*"
	r"|\b(?:text|logo)s?(?: overlays?)?\s+(?:is|are)?\s*(?:added|inserted|overlaid|laid)\b[^.!?;\n]*[.!?;]?\s*"
	# Notes for the editor ("the text overlay in post-production", "do not let AI rewrite the logo or specifications"):
	# even as a prohibition, naming text and logos makes a video model paint them.
	r"|[^.!?;\n]*\b(?:post[- ]production|text overlays?|specifications|rewrite the logo)\b[^.!?;\n]*[.!?;]?\s*",
	re.I,
)


def without_overlay_text(text):
	"""The text without directions to show words, a logo or a call to action (they are added when the film is finished)."""
	return re.sub(r"[ \t]{2,}", " ", OVERLAY_DIRECTIVE.sub(" ", str(text or ""))).strip()


# Legs/feet also describe furniture and products. Their owner must come from
# the authored scene contract; guessing an actor corrupts support geometry.
BODY_PART = re.compile(r"\b(hands?|fingers?|arms?|paws?|fists?|palms?)\b", re.I)
NON_ACTOR_PART = re.compile(r"\b(?:table|chair|sofa|armchair|clock|watch)(?:'s)?\s+(?:[\w-]+\s+){0,4}$", re.I)
NEGATED_PART = re.compile(r"\b(?:no|never|without|neither|nor|avoid|forbid|forbidden)\b", re.I)
OWNED = re.compile(r"(?:\b(?:its|his|her|their|my|your|own)|'s)\s+(?:\w+\s+){0,5}$", re.I)


def scene_actor(shot, project):
	"""The plain name of who acts in the scene (its first cast member), or None for a scene without a cast."""

	def field(row, key):
		return row.get(key) if hasattr(row, "get") else getattr(row, key, None)

	labels = {
		field(row, "asset_version"): field(row, "label")
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	identities = {
		field(row, "asset_version"): field(row, "identity_key")
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	actors = {}
	for reference in getattr(shot, "references", None) or []:
		role = frappe.scrub(field(reference, "reference_role") or field(reference, "input_role") or "")
		label = labels.get(field(reference, "asset_version"))
		if role in ("character", "person", "people", "talent") and label:
			name = cast_name(label, project, person=role != "character")
			actors[identities.get(field(reference, "asset_version")) or name] = name
	# Ambiguous limbs in a multi-actor scene must be assigned by the authored
	# contract, not silently attributed to the first reference in the roster.
	return next(iter(actors.values())) if len(actors) == 1 else None


def owned_body_parts(text, owner):
	"""A hand, arm or paw the text names with no owner ("close-up of hand + table") becomes the actor's own ("the
	mascot's own hand"): unowned, the image and video models draw a stranger's hand doing the action."""
	if not owner:
		return text

	def own(match):
		before = text[max(0, match.start() - 100) : match.start()]
		# A suffix preserves determiners and modifiers ("one rounded paw") and
		# avoids rewriting them into "one rounded the mascot's own paw".
		after = text[match.end() :]
		clause = re.split(r"[.!?;\n]", before)[-1]
		# Preserve prohibitions, existing suffix ownership, and object parts.
		# "No human hands" must never become an instruction to give the actor
		# human hands, and "chair arms" must remain attached to the chair.
		if (
			OWNED.search(before)
			or NON_ACTOR_PART.search(before)
			or NEGATED_PART.search(clause)
			or re.match(r"\s+(?:belonging\s+to|of)\b", after, re.I)
		):
			return match.group(0)
		return f"{match.group(0)} belonging to {owner}"

	return BODY_PART.sub(own, str(text or ""))


def _no_outsiders(shot, project):
	"""The rule that keeps strangers' body parts out of a scene with a cast."""
	actor = scene_actor(shot, project)
	if not actor:
		return ""
	return (
		f"{actor[:1].upper()}{actor[1:]} is the one doing the action: every hand, arm, paw or other body part in the picture "
		"belongs to the cast and looks exactly like the cast in its picture (an illustrated character's paw or hand has its own "
		"surface, colour and shape, never bare human skin or human fingers); no other person and no outside hand or arm appears. "
	)


def _scrub_for_drawing(text):
	"""Make a planner's image description safe for a generated starting frame.

	Extreme close-ups become a medium shot so the selected reference subject can
	be composed in its setting. Quantities and quoted words are removed because
	image models commonly render them as incorrect text.
	"""
	text = QUANTITY.sub("", without_overlay_text(text))
	text = EXTREME_CLOSEUP.sub("medium shot", text)
	text = re.sub(r"\s{2,}", " ", text)
	return re.sub(r"\s+([.,;:!?])", r"\1", text).strip()


def _first_actions(shot):
	"""The first sentences of the scene's movement text: what the characters are doing at the start."""
	text = getattr(shot, "generation_prompt", None) or ""
	paragraphs = [p for p in text.split("\n\n") if p.strip() and not p.lstrip().startswith("Audio:")]
	sentences = re.split(r"(?<=[.!?])\s+", " ".join(paragraphs[:1]))
	return _scrub_for_drawing(" ".join(sentences[:2]))[:260]


def _size_sentence(sized):
	"""Say how much taller the largest character is than each smaller one: the image model ignores the board's sizes."""
	if len(sized) < 2:
		return ""
	largest = max(scale for _name, scale in sized)
	big = next(name for name, scale in sized if scale == largest)
	parts = []
	for name, scale in sized:
		if scale < largest * 0.85 and name != big:
			times = largest / scale
			parts.append(
				f"{name} is much smaller: {big} is about {times:.1f} times taller, stands upright on two legs and "
				f"towers over {name}, who comes up only to {big}'s waist"
			)
	return ("Scale matters: " + "; ".join(parts) + ". ") if parts else ""


CAMERA_MOVE = re.compile(
	r"->|→|\b(?:zoom\w*|pan\w*|tilt\w*|dolly|push(?:es|ing)?(?:-|\s)in|pull(?:s|ing)?(?:-|\s)(?:back|out)|track\w*|orbit\w*|"
	r"crane|whip|fast-paced|moves?|moving)\b|\bto\s+(?:a\s+)?(?:close|medium|wide|extreme|macro)",
	re.I,
)


def _camera_locked(shot):
	plan = getattr(shot, "motion_plan_json", None)
	if isinstance(plan, str):
		try:
			plan = json.loads(plan)
		except ValueError:
			return False
	return isinstance(plan, dict) and plan.get("camera_motion") == "locked"


def camera_moves(shot):
	"""Whether the sheet's camera direction for this scene moves the camera ("wide to medium", "top-down -> macro")."""
	if _camera_locked(shot):
		return False
	text = getattr(shot, "generation_prompt", None) or ""
	direction = re.search(r"\bCamera:\s*([^\n]*)", text)
	return bool(direction and CAMERA_MOVE.search(direction.group(1)))


def opening_framing(shot):
	"""Use structured framing first, then the legacy camera opening if supplied.

	An unplanned scene keeps its authored image composition without an invented
	crop prefix. Legacy extreme close-ups retain their historical drawing scrub.
	"""
	from joymedia.services.planning.shot_structure import framing_text, structure_for

	structure = structure_for(shot)
	if structure:
		return framing_text(structure)
	text = getattr(shot, "generation_prompt", None) or ""
	direction = re.search(r"\bCamera:\s*([^\n]*)", text)
	if not direction:
		# The authored image prompt owns composition when a scene has not yet
		# been structurally planned. Shot index is not evidence of its crop.
		return ""
	start = re.split(r"\s*(?:->|→|\bto\b)\s*", direction.group(1), maxsplit=1)[0]
	return _scrub_for_drawing(re.split(r"(?<=[.!?])\s", start)[0]).strip(" .")


def _translation_key(kind, text):
	"""A cache key for a translation: it changes with the translator model, so a model swap never serves old answers."""
	from joymedia.services.runtime.endpoints import endpoint

	try:
		model = endpoint("translator").model
	except frappe.ValidationError:
		model = ""
	return f"joymedia:{kind}:{model}:{hashlib.sha1(str(text).encode()).hexdigest()}"


def _english(text, project):
	"""The sheet's text in English, translated once and cached (prompts are compiled at every render)."""
	from joymedia.services.planning.production import translate

	text = " ".join(str(text or "").split())
	if not text:
		return ""
	key = _translation_key("sheet_english", text)
	english = frappe.cache.get_value(key)
	if english is None:
		english = (translate(text, project) or "").strip()
		frappe.cache.set_value(key, english)
	return english


def sheet_brief(project):
	"""The sheet's brief in English for the prompts: {"tone", "usp", "characters": {role: description}}.

	The scene rows say what happens; the brief says how it should feel (Tone & Mood), what the product is good at
	(USP) and who the characters are ("Gấu trắng mẹ - nhân vật chính", a white bear mother, the main character). Each
	character line is matched to a reference by its family role (planning/roles.py)."""
	from joymedia.services.planning.roles import family_role

	name = project.get("media_project") or project.get("name")
	source = frappe.db.get_value("Media Project", name, "storyboard_source_json") if name else None
	try:
		stored = frappe.parse_json(source or "{}") or {}
	except (TypeError, ValueError):
		stored = {}
	metadata = (stored.get("selected_demo") or {}).get("metadata") or {}
	brand = stored.get("brand") or {}
	characters = {}
	for line in re.split(r"\n+", str(metadata.get("characters") or "")):
		line = line.strip(" -•*\t")
		role = family_role(line)
		if line and role and role not in characters:
			characters[role] = _english(line, project).strip(" .")
	return {
		"tone": _english(metadata.get("tone_mood"), project).strip(" ."),
		"usp": _english(metadata.get("usp"), project).strip(" ."),
		"characters": characters,
		# The Brand sheet: the film's one visual style, and what may and may not be claimed.
		"style": _english(brand.get("visual_style"), project).strip(" ."),
		"claims": _english(brand.get("claims"), project).strip(" ."),
		"avoid": _english(brand.get("avoid"), project).strip(" ."),
		"mandatories": str(brand.get("mandatories") or "").strip(),
	}


def scene_rules(shot):
	"""The scene's own rules (the sheet's Logic / Continuity column), from its prompt's "Rules:" paragraph."""
	text = (
		getattr(shot, "generation_prompt", None)
		or (shot.get("generation_prompt") if hasattr(shot, "get") else "")
		or ""
	)
	found = re.search(r"(?:^|\n\n)Rules:\s*(.+?)(?=\n\n|$)", text, re.S)
	return " ".join(found.group(1).split()) if found else ""


def keep_rules(shot, project):
	"""What must stay as is for each picture in the scene (the References sheet), in English, preserving each reference's authored rule."""

	def field(row, key):
		return row.get(key) if hasattr(row, "get") else getattr(row, key, None)

	rows = {
		field(row, "asset_version"): row
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	rules = []
	for reference in getattr(shot, "references", None) or []:
		row = rows.get(field(reference, "asset_version"))
		rule = field(row, "keep_rule") if row else ""
		rule = without_overlay_text(_english(rule, project)).strip(" .;,") if rule else ""
		if rule:
			role = _role_of(reference)
			name = (
				cast_name(
					field(row, "label") or "",
					project,
					person=frappe.scrub(field(reference, "reference_role") or "") != "character",
				)
				if role == "character"
				else "the advertised product"
				if role == "product"
				else "the place"
				if role == "environment"
				else "the logo"
				if role == "logo"
				else "the supplied reference"
			)
			rules.append(f"{name}: {rule}")
	return "; ".join(dict.fromkeys(rules))


def _mood(project):
	"""The sheet's Tone & Mood, visual style and what must not be shown: one line for the image and video models,
	the same in every scene."""
	brief = sheet_brief(project)
	return (
		(f"Mood: {brief['tone']}. " if brief["tone"] else "")
		+ (f"Visual style: {brief['style']}. " if brief["style"] else "")
		+ (f"Never show: {brief['avoid']}. " if brief["avoid"] else "")
	)


def product_identity(project, shows=True):
	"""Describe the advertised product from project data without inventing its form.

	Exact geometry and branding come from its selected reference asset.  This function
	intentionally does not infer category-specific rules from a product name: those
	belong in the creator's brief or an approved workflow version.
	"""
	from joymedia.services.planning.production import brand_words, translate

	name = str(project.get("product_name") or "").strip()
	if not name:
		return ""
	key = _translation_key("product_identity", name)
	english = frappe.cache.get_value(key)
	if english is None:
		english = translate(name, project) or ""
		# An all-capitals name capitalises every word, so only mixed-case text tells a brand from a common word.
		brands = (
			brand_words(name)
			if not name.isupper()
			else {w.casefold() for w in name.split() if w.isascii() and w.isalpha()}
		) | (brand_words(english) if not english.isupper() else set())
		# Quantities and their units ("400 SHEETS / 4 LAYERS"), also in an unclosed bracket, and the separators left.
		english = re.sub(
			r"\([^)]*\)?|\d[\w.,-]*(?:\s*(?:sheets?|layers?|ply|pcs|pieces|rolls?|packs?|g|kg|ml|l)\b)?",
			" ",
			english,
			flags=re.I,
		)
		english = re.sub(r"\s*[/•|]\s*", " ", english)
		english = " ".join(w for w in english.split() if w.strip(",.;:-").casefold() not in brands).strip(
			" ,.-"
		)
		english = english.lower() if english.isupper() else english
		english = english if re.search(r"[a-z]{3,}", english, re.I) else ""
		frappe.cache.set_value(key, english)
	if not english:
		return ""
	if not shows:
		return ""
	# Only what the product is: a selling point is a message, and a drawing model prints a message as text in the picture.
	return f"The advertised product is {english}. "


def _locked_product(shot):
	"""Whether the real product pack is pasted into this scene's first frame and held exactly through its video."""
	from joymedia.services.keyframes.overlay import pasted_references

	references = getattr(shot, "references", None) or []
	mode = getattr(shot, "character_mode", None) or "Paste exact art"
	return any(item["role"] == "product" for item in pasted_references(references, mode))


HOLDING = re.compile(
	r"\b(?:hold(?:s|ing)?|cradl(?:es?|ing)|carr(?:y|ies|ying)|hug(?:s|ging)?|clutch(?:es|ing)?|embrac(?:es?|ing)|"
	r"present(?:s|ing)?|in (?:her|his|its|their) arms)\b[^.!?]*\b(?:pack|bag|box|packet|product|carton)s?\b",
	re.I,
)


def holds_product(shot):
	"""Whether the opening action calls for a character to hold the referenced product."""
	from joymedia.services.keyframes.locations import shot_views
	from joymedia.services.project.context import scene_direction

	if not _locked_product(shot) or shot_views(
		shot if hasattr(shot, "get") else frappe._dict(views_json=getattr(shot, "views_json", None))
	):
		return False
	action = scene_direction(getattr(shot, "generation_prompt", None) or "")["action"]
	return bool(HOLDING.search(re.split(r"(?<=[.!?])\s+", action)[0] if action else ""))


def _product_note(shot, project):
	"""Reserve an unobstructed composition area for an exact product reference asset."""
	from joymedia.services.keyframes.overlay import closes_film

	if not _locked_product(shot):
		return ""
	if holds_product(shot):
		return (
			"As the scene says, the character holds the advertised product reference in front of its body, fully visible "
			"and unobstructed. Do not draw a substitute product. "
		)
	if closes_film(shot, project):
		return (
			"This is the closing shot of the advertisement: keep a central area clear because the approved product asset "
			"will be composed there as the hero. Supporting subjects must not cover it. "
		)
	return (
		"Keep an unobstructed area in the composition for the approved product asset. Characters and other objects must "
		"not cover that area, and do not draw a substitute product. "
	)


def _with_opening_staging(prompt, shot):
	from joymedia.services.scene.artwork import placements
	from joymedia.services.scene.contract import opening_instruction

	plan = shot.get("motion_plan_json")
	artwork = placements(plan)
	if artwork:
		# The compositor supplies these objects after inference. Asking the image
		# model to supply them too creates duplicates and redraws source branding.
		plan = json.loads(plan) if isinstance(plan, str) else dict(plan)
		contract = dict(plan.get("scene_contract") or {})
		protected = {row["entity"] for row in artwork if row.get("entity")}
		for field, keys in (
			{
				"entities": ("id",),
				"counts": ("entity",),
				"parts": ("entity",),
				"properties": ("entity",),
				"relations": ("subject", "object"),
				"proportions": ("subject", "reference"),
			}.items()
			if contract
			else []
		):
			contract[field] = [
				row for row in contract.get(field, []) if not any(row.get(key) in protected for key in keys)
			]
		if contract:
			plan["scene_contract"] = contract
	staging = opening_instruction(plan, shot.get("duration_seconds"))
	prompt = (
		f"{staging}\nDraw only this opening state, before the first timed action. "
		"Do not advance it to a later action or result described in the scene context below.\n\n" + prompt
		if staging
		else prompt
	)
	from joymedia.services.planning.shot_structure import framing_text, structure_for, visibility_instruction

	structure = structure_for(shot)
	if structure:
		value = json.loads(plan) if isinstance(plan, str) else (plan or {})
		prompt += (
			"\n\nNew keyframe composition: "
			+ framing_text(structure)
			+ ". Keep the declared action area visible; do not perform later actions in the opening still. "
		)
		prompt += visibility_instruction(structure, value.get("scene_contract"))
	return prompt


def _draw_prompt(shot, project):
	"""The keyframe prompt for "Draw in scene", independent of an image-model family."""
	from joymedia.services.keyframes.overlay import describe_colours, pasted_references, usable_setting
	from joymedia.services.planning.roles import family_role, role_look

	brief = sheet_brief(project)
	from joymedia.services.scene.contract import opening_instruction

	structured_opening = opening_instruction(shot.get("motion_plan_json"), shot.get("duration_seconds"))

	# The reviewed still-frame direction is an independent control. Falling back
	# to the motion paragraph first made first-frame edits silently ineffective.
	action = _scrub_for_drawing(getattr(shot, "image_prompt", None) or "") or _first_actions(shot)
	labels = {
		(row.get("asset_version") if hasattr(row, "get") else getattr(row, "asset_version", None)): (
			row.get("label") if hasattr(row, "get") else getattr(row, "label", None)
		)
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	scales = {
		(row.get("asset_version") if hasattr(row, "get") else getattr(row, "asset_version", None)): float(
			(row.get("scale") if hasattr(row, "get") else getattr(row, "scale", None)) or 1
		)
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	briefs, sized = [], []
	for reference in getattr(shot, "references", None) or []:
		if _role_of(reference) != "character":
			continue
		version = (
			reference.get("asset_version")
			if hasattr(reference, "get")
			else getattr(reference, "asset_version", None)
		)
		if labels.get(version):
			colours = describe_colours(version)
			name = _describe_character(labels[version], project)
			# A family role changes only build and posture; the reference identity stays.
			look = role_look(labels[version])
			described = brief["characters"].get(family_role(labels[version]) or "")
			if described:
				look = f"the advertiser describes it as: {described}" + (f"; {look}" if look else "")
			briefs.append(
				f"{name} is the character of picture {len(briefs) + 1}"
				+ (
					f" ({colours}; preserve the reference palette)"
					if colours and "brown" not in colours.split(",")[0]
					else (f" ({colours})" if colours else "")
				)
				+ (f", {look}" if look else "")
			)
			sized.append((name.split(",")[0], scales.get(version, 1.0)))
	cast = "; ".join(dict.fromkeys(briefs))
	size_rule = _size_sentence(sized)
	raw_roles = {
		frappe.scrub(
			(r.get("reference_role") if hasattr(r, "get") else getattr(r, "reference_role", "")) or ""
		)
		for r in getattr(shot, "references", None) or []
	}
	has_character, has_person = "character" in raw_roles, bool(raw_roles & {"person", "people", "talent"})
	if not has_character:
		from joymedia.services.planning.shot_structure import structure_for

		structured = structure_for(shot)
		person = (
			"Preserve the reference person's identity and the appearance of visible body parts. Use only the authored opening pose and framing; a detail view does not require an additional face or full body. "
			if structured
			else "The person shown in the reference photo is in the scene, keeping their own face and look, in a natural pose doing what the scene describes, seen in a medium or wide shot. "
		)
		return (
			f"{usable_setting(getattr(shot, 'setting_prompt', None))} {action}\n\n"
			+ (person if has_person else "")
			+ product_identity(project, shows="product" in raw_roles)
			+ (
				"The referenced product is physically present in the authored opening state, with its visible surface and contact area shown. Show the product itself, not only its background. "
				if "product" in raw_roles and not _locked_product(shot)
				else ""
			)
			+ "Natural light, realistic composition."
		)
	product_note = _product_note(shot, project)
	product_note = (
		product_identity(
			project, shows=any(_role_of(r) == "product" for r in getattr(shot, "references", None) or [])
		)
		+ product_note
	)
	# The sheet's opening framing, so a close-up scene does not come out as a wide view of the room.
	framing = opening_framing(shot)
	setting = usable_setting(getattr(shot, "setting_prompt", None)).rstrip(". ")
	# The image stage receives cast, then non-pasted products, then the place.
	# Counting only cast pointed "the room of picture 2" at the product photo
	# whenever a JPEG pack was supplied beside a single mascot.
	pasted = {
		item["asset_version"]
		for item in pasted_references(getattr(shot, "references", None) or [], "Draw in scene")
	}
	product_pictures = sum(
		_role_of(ref) == "product" and ref.get("asset_version") not in pasted
		for ref in getattr(shot, "references", None) or []
	)
	place_picture = len(briefs) + product_pictures + 1
	return (
		owned_body_parts(
			(f"{framing[:1].upper()}{framing[1:]}. " if framing else "") + action, scene_actor(shot, project)
		)
		+ "\n\n"
		+ _no_outsiders(shot, project)
		+ (f"Cast: {cast}. " if cast else "")
		+ "Each character is exactly the subject of its picture: preserve its face, colours, markings, accessories, "
		"body design and surface finish (a smooth surface stays smooth; never add fur, hair or texture it does not have). Each cast identity appears once, in the authored opening pose, not the pose or objects in their reference image. Characters printed on product packaging stay flat artwork, not additional cast. Do not perform later scene actions. "
		+ size_rule
		+ product_note
		+ f"The place: {setting}"
		+ (
			f", the room of picture {place_picture}: the same furniture, window and light"
			if "environment" in raw_roles
			else ""
		)
		+ ". "
		+ (f"In this scene: {scene_rules(shot)}. " if not structured_opening and scene_rules(shot) else "")
		+ (f"Must stay as is: {keep_rules(shot, project)}. " if keep_rules(shot, project) else "")
		+ _mood(project)
		+ "Natural, coherent lighting and composition."
	)


def _character_names(shot, project):
	"""Labels of the Character references the scene uses, from the project's reference list."""

	def field(row, key):
		return row.get(key) if hasattr(row, "get") else getattr(row, key, None)

	labels = {
		field(row, "asset_version"): field(row, "label")
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	names = []
	for reference in getattr(shot, "references", None) or []:
		role = frappe.scrub(field(reference, "reference_role") or field(reference, "input_role") or "")
		label = labels.get(field(reference, "asset_version"))
		if role in ("character", "person", "people", "talent") and label:
			from joymedia.services.keyframes.overlay import describe_colours

			# The video model prints words it is given onto objects, so the cast is named in plain English,
			# never by a label in the advertiser's language.
			name = cast_name(label, project, person=role != "character")
			if not any(existing.split(" (")[0] == name for existing in names):
				colours = describe_colours(field(reference, "asset_version")) if role == "character" else ""
				# Preserve colours explicitly because a generated frame may otherwise drift.
				names.append(f"{name} ({colours}; {_colour_rule(colours)})" if colours else name)
	return names


def _colour_rule(colours):
	return "keep exactly these colours"


def _timed_events(cues, duration):
	"""Concrete sound events with a time each, the way the video workflow's own sample writes its `Audio:` line.

	"paper rustling, a tap" becomes "paper rustling at 1.2s, a tap at 3.7s": a timed list of events steers the
	model to those sounds and leaves gaps between them, where a vague description gets a continuous bed.
	"""
	events = [e.strip(" .") for cue in cues for e in re.split(r"[,;]|\band\b", cue) if e.strip(" .")][:5]
	step = max(0.5, float(duration or 5.0)) / len(events)
	return ", ".join(f"{event} at {round(step * (index + 0.5), 1)}s" for index, event in enumerate(events))


def _audio_line_last(prompt, sound_effects_only=False, duration=5.0):
	"""Move the scene's `Audio:` paragraph to the end of the video prompt.

	The video workflow's own sample prompt ends with its `Audio:` line. Left in the middle of a long prompt
	(followed by fidelity, identity and timing text) the sound direction is easily ignored. The workflow
	generates voice, effects and music in one pass and exposes no level for each, so "sound effects only"
	is asked for in that line: music cues are dropped and speech and music are ruled out.
	"""
	paragraphs = str(prompt).split("\n\n")
	audio = [p for p in paragraphs if p.lstrip().startswith("Audio:")]
	if sound_effects_only:
		cues = [
			part.strip()
			for line in audio
			for part in line.lstrip()[len("Audio:") :].strip().rstrip(".").split(";")
			if part.strip() and not part.strip().casefold().startswith("music")
		]
		# A vocal sound inside a cue ("... Baby bear's giggling laughter.") is dropped with its sentence.
		cues = [
			" ".join(
				sentence for sentence in re.split(r"(?<=[.!])\s+", cue) if not VOCAL_SOUND.search(sentence)
			)
			for cue in cues
		]
		cues = [cue.rstrip(". ") for cue in cues if cue]
		if not cues:
			# Missing cues must not invent product-specific sounds in unrelated scenes.
			audio = [f"Audio: silence. {NO_VOICE_OR_MUSIC}"]
		else:
			audio = [
				f"Audio: {_timed_events(cues, duration)}; silence between the sounds. {NO_VOICE_OR_MUSIC}"
			]
	if not audio:
		return prompt
	rest = [p for p in paragraphs if not p.lstrip().startswith("Audio:")]
	return "\n\n".join(rest + audio)


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
