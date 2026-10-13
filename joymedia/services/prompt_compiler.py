import hashlib
import json
import re

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
	def finish(text):
		# Continuation segments are written from the creative text, so they need the cast and audio rules too.
		if prompt_source != "motion" or segment_count == 1:
			return text
		if shot.get("references") if hasattr(shot, "get") else getattr(shot, "references", None):
			text = f"{text}\n\n{_identity_guard(shot, project)}"
		return _audio_line_last(
			text, sound_effects_only=project.get("soundtrack_mode") in ("Sound effects only", "Separate effects layer"),
			duration=(float(segment_effective_frames) / float(fps)) if segment_effective_frames and fps else 5.0,
		)

	if asset_versions:
		from .film_director import reference_preamble

		# Continuations receive the same reference images as the first segment.
		base = f"{reference_preamble(asset_versions, project.get('references') or [])}\n\n{base}"
	if segment_count == 1 or prompt_source == "image":
		# A still image has no segments or timing; the action plan belongs to the video stage.
		return base
	has_references = bool(shot.get("references") if hasattr(shot, "get") else getattr(shot, "references", None))
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
	if prompt_source == "motion" and has_references:
		# The action plan is written from the beat's own text, so it needs the same treatment.
		timing = _scrub_printable(timing, **_scrub_options(shot, project))
	if segment_index == 1:
		return finish((
			f"{base}\n\nThis is segment 1 of {segment_count}. "
			"Begin the planned action naturally.\n\n"
			f"{timing}"
		).strip())
	return finish((
		f"{base}\n\nThis is continuation segment {segment_index} of {segment_count}. "
		"Continue seamlessly from the previous clip's exact last frame with the same motion, light and sound. "
		"Do not restart or reintroduce the action.\n\n"
		f"{timing}"
	).strip())


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

	if prompt_source == "motion" and getattr(shot, "references", None):
		prompt = "\n\n".join(
			_scrub_printable(part, **_scrub_options(shot, project)) if not part.lstrip().startswith("Audio:") else part
			for part in prompt.split("\n\n")
		)
	if prompt_source == "image":
		from .subject_overlay import DRAW, EMPTY_SETTING, PASTE, pasted_references, usable_setting

		mode = getattr(shot, "character_mode", None) or PASTE
		references = getattr(shot, "references", None) or []
		if mode == DRAW and any(_role_of(r) in ("character", "person") for r in references):
			return _draw_prompt(shot, project)
		if pasted_references(references, mode):
			# The real characters and products are pasted in afterwards, so the image model gets the place only.
			# Anything else in the prompt (names, actions, fidelity rules) would be drawn into it.
			return f"{usable_setting(getattr(shot, 'setting_prompt', None))}\n\n{EMPTY_SETTING}"

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
			"Reference fidelity: show only the intended referenced product. Keep its exact shape, material, "
			"colours, proportions, mascot artwork and brand logo; do not swap, merge, deform or invent products or "
			"logos. Do not write or redraw words: small print and label text stay a soft, unreadable texture."
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
	if prompt_source == "motion" and getattr(shot, "references", None):
		prompt = f"{prompt}\n\n{_identity_guard(shot, project)}"
	if prompt_source == "motion":
		timing = temporal_timing_instruction(shot, is_final=is_final)
		if timing:
			prompt = f"{prompt}\n\n{timing}"
		prompt = _audio_line_last(
			prompt, sound_effects_only=project.get("soundtrack_mode") in ("Sound effects only", "Separate effects layer"),
			duration=float(getattr(shot, "duration_seconds", None) or 5.0),
		)
	return prompt.strip()


def _identity_guard(shot, project):
	"""The cast, colour and no-extras rules every video segment of a scene with references must carry.

	The video model keeps no identity of its own beyond the supplied frame and tends to redesign a character the
	moment the camera moves in close, or to invent another one for any animal, person or product the text names.
	State the cast once, then resolve every name and body part against it.
	"""
	names = _character_names(shot, project)
	inventory = first_frame_inventory(shot, project)
	if len(names) > 1:
		who = (
			f"The only characters in this scene are {' and '.join(names)}. They are different individuals: never "
			"merge them, swap them, or draw one of them twice. "
			f"{_kinship_hint(names)}Every hand, arm or paw is its own character's body, never a separate person's. "
			"No other character, animal, person or human hand appears. "
		)
	elif names:
		who = (
			f"The only character in this scene is {names[0]}. Every bear, cub, mother, baby, person or other "
			"character named in this prompt is this one, and every hand, arm or paw is its own, never a separate "
			"person's. No other character, animal, person or human hand appears. "
		)
	else:
		who = (
			"Every character, animal or person named in this prompt is the one character shown in the supplied "
			"first frame, and every hand or paw is that character's own. "
		)
	return (
		(f"The first frame contains exactly: {inventory}. Nothing else is added: no other character, box, carton or "
		   "product. Whatever the text says anyone does, the characters listed above do it. " if inventory else "")
		+ "Scene fidelity: the supplied first frame is the truth for the place, the lighting, the time of day, the "
		"characters and every object. Keep them for the whole clip; this text describes only what moves, and any "
		"description of a different place, lighting or object in it is ignored. Keep the camera framing of the "
		"first frame: allow at most a very slight, slow push-in, so that every character and product stays in view "
		"and unchanged. Never print quantities, names or words on any object. "
		f"Identity consistency: {who}Every product is the one shown in the first frame; never add another product, "
		"carton or packaging, or a second copy. Add no text, letters, numbers or captions anywhere except the brand "
		"logo. Keep everything exactly as shown (same colours, fur or material, face and proportions) in every "
		"camera angle, including close-ups; never redesign or recolour it."
	)


NO_VOICE_OR_MUSIC = (
	"Sound effects only: no speech, no dialogue, no narration, no singing, no laughing or other vocal sounds, "
	"no background music."
)
VOCAL_SOUND = re.compile(r"\b(laugh\w*|giggl\w*|voice\w*|speak\w*|speech|talk\w*|sing\w*|song|cry\w*|scream\w*|shout\w*|whisper\w*|say\w*|hum\w*|gasp\w*)\b", re.I)


MOTHER_WORDS = re.compile(r"\b(mẹ|mom|mum|mother|mama)\b", re.I)
KID_WORDS = re.compile(r"\b(con|kid|baby|child|cub|boy|girl)\b", re.I)


def _kinship_hint(names):
	"""Which name a mother and which a kid refers to, when the names say so."""
	mother = next((n for n in names if n.startswith("the mother mascot")), None)
	kid = next((n for n in names if n.startswith("the kid mascot")), None)
	if not (mother and kid):
		return ""
	return (
		"A mother, mom or mama named in the text is the mother mascot; a baby, kid, child or cub named in the text "
		"is the kid mascot. "
	)


PRINTABLE = re.compile(
	r"\(\s*\d[^)]*\)|\b\d+\s*(?:packs?|boxes|box|sheets?|ply|layers?|rolls?|pcs|pieces)\b|[\"“”][^\"“”]*[\"“”]"
	# Where things stand is fixed by the first frame; a placement in the text makes the model draw a second copy.
	r"|\b(?:at|in|on|to|from)\s+(?:the\s+)?(?:(?:top|bottom|upper|lower)[ -]*)?(?:left|right|centre|center)"
	r"(?:[ -]*(?:hand\s+)?(?:corner|side|of the (?:frame|screen)))?(?:\s+of the (?:frame|screen))?",
	re.I,
)


PACKAGING = re.compile(r"\b(?:(?:large|big|huge|giant|bulk)\s+)?(boxes|box|cartons?|cases?|crates?)\b|\bbulk packaging\b", re.I)
CAMERA_ZOOM = re.compile(r"[^.!?]*\b(?:zoom\w*|push(?:es|ing)?[ -]in|dolly\w* in)\b[^.!?]*[.!?]?", re.I)


def _scrub_printable(text, packaging=True, zoom=True):
	"""Make movement text safe for a first frame: no printed quantities or quoted words, no placement, no extras.

	The video model prints whatever words it is given onto objects and draws a second copy of anything placed
	somewhere new. `packaging` turns a box or carton the text names into the product packs in the frame (the model
	invents one otherwise); `zoom` removes zoom sentences (a zoom enlarges pasted products until their printing is
	redrawn). Both are decided per scene by `_scrub_options`.
	"""
	text = SIMILE.sub("", PRINTABLE.sub("", str(text or "")))
	text = TEXTURE_WORDS.sub("", text)
	if packaging:
		text = PACKAGING.sub(lambda m: "product packs" if (m.group(1) or "").lower() in ("boxes",) else "product pack", text)
	if zoom:
		text = CAMERA_ZOOM.sub("", text)
	text = re.sub(r"\s{2,}", " ", text)
	return re.sub(r"\s+([.,;:!?])", r"\1", text).strip()


# Similes and texture words describe how something looks, and the video model takes them literally ("as if leaning
# into cloud-soft fur" grows fur on a smooth mascot). The first frame already shows how everything looks.
SIMILE = re.compile(r"[,;]?\s*\b(?:as if|as though|as (?:a|an|the)\b|like (?:a|an|the)\b|resembling)\b[^.;!?]*", re.I)
TEXTURE_WORDS = re.compile(r"\b(?:fluffy|furry|fuzzy|cloud[- ]?like|cloud[- ]?soft|woolly|velvety|silky|plush)\b[ -]*", re.I)

PACKAGING_WORDS = re.compile(r"\b(box|boxes|carton|cartons|case|cases|crate|crates|hộp|thùng)\b", re.I)


def _scrub_options(shot, project):
	"""Which of the optional scrub rules suit this scene.

	Packaging nouns are left alone when the scene's own product is a box or carton (its label says so), and zooms
	are left alone unless a real product image is pasted into the first frame.
	"""
	from .subject_overlay import pasted_references

	references = (shot.get("references") if hasattr(shot, "get") else getattr(shot, "references", None)) or []
	labels = {
		(row.get("asset_version") if hasattr(row, "get") else getattr(row, "asset_version", None)):
		(row.get("label") if hasattr(row, "get") else getattr(row, "label", None)) or ""
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	product_labels = " ".join(
		labels.get(r.get("asset_version") if hasattr(r, "get") else getattr(r, "asset_version", None), "")
		for r in references if _role_of(r) == "product"
	)
	pasted_product = any(p["role"] == "product" for p in pasted_references(references, "Paste exact art"))
	return {"packaging": not PACKAGING_WORDS.search(product_labels), "zoom": pasted_product}


def _scrub_paragraphs(text, **options):
	"""Scrub the movement paragraphs of a prompt; the audio line is left as it is."""
	return "\n\n".join(
		part if part.lstrip().startswith("Audio:") else _scrub_printable(part, **options) for part in str(text).split("\n\n")
	)


def _display_name(label, number):
	"""A plain English name for a character: its role when the label gives one, else the ASCII label, else a number."""
	if MOTHER_WORDS.search(label):
		return "the mother mascot"
	if KID_WORDS.search(label):
		return "the kid mascot"
	base = label.split(" (")[0].strip()
	return base if base.isascii() and base else f"character {number}"


def first_frame_inventory(shot, project):
	"""What the approved first frame contains, from the scene's references: characters left to right, products, logo."""
	def field(row, key):
		return row.get(key) if hasattr(row, "get") else getattr(row, key, None)

	references = getattr(shot, "references", None) or []
	if not any(_role_of(r) in ("character", "person", "product", "logo") for r in references):
		return ""
	names = [n.split(" (")[0] for n in _character_names(shot, project)]
	products = sum(1 for r in references if _role_of(r) == "product")
	ordered = (getattr(shot, "character_mode", None) or "Paste exact art") != "Draw in scene"
	parts = []
	if names:
		parts.append(f"{'from left to right ' if len(names) > 1 and ordered else ''}{' and '.join(names)}")
	if products:
		parts.append(f"{'in front of them ' if names else ''}{products} small product pack{'s' if products > 1 else ''}")
	if any(_role_of(r) == "logo" for r in references):
		parts.append("the brand logo at the top left")
	return ", ".join(parts)


def _role_of(reference):
	"""A reference's role for naming and counting: a real person counts as a character in a scene."""
	role = frappe.scrub(
		(reference.get("reference_role") if hasattr(reference, "get") else getattr(reference, "reference_role", "")) or ""
	)
	return "character" if role in ("person", "people", "talent") else role


def _character_labels(shot, project):
	"""The labels of the Character references the scene uses, in order."""
	def field(row, key):
		return row.get(key) if hasattr(row, "get") else getattr(row, key, None)

	labels = {
		field(row, "asset_version"): field(row, "label")
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	return [
		labels[field(r, "asset_version")]
		for r in getattr(shot, "references", None) or []
		if _role_of(r) == "character" and labels.get(field(r, "asset_version"))
	]


def _describe_character(label):
	"""What the image model is told about a character: the label's own English detail, else its role."""
	detail = label.split(" (", 1)[1].rstrip(")") if " (" in label else ""
	if detail and detail.isascii():
		return detail
	return _display_name(label, 1)


HUMAN_BODY = re.compile(r"\b(hands?|fingers?)\b", re.I)
EXTREME_CLOSEUP = re.compile(r"\b(?:macro|extreme|super)(?:[ -]+(?:macro|extreme|super))*[ -]+close[ -]?ups?\b|\bmacro\b", re.I)
QUANTITY = re.compile(r"\(\s*\d[^)]*\)|\b\d+\s*(?:packs?|boxes|box|sheets?|ply|layers?|rolls?|pcs|pieces)\b(?:\s+of)?|[\"“”][^\"“”]*[\"“”]", re.I)


def _scrub_for_drawing(text):
	"""Make a planner's image description safe for drawing a family scene of mascots.

	A hand is the character's own paw (the model would draw a person's hand), an extreme close-up becomes a
	medium shot (the characters must be seen acting in the room), and quantities and quoted words go (they get
	drawn as letters).
	"""
	text = QUANTITY.sub("", str(text or ""))
	text = EXTREME_CLOSEUP.sub("medium shot", text)
	text = HUMAN_BODY.sub(lambda m: "paws" if m.group(1).lower().endswith("s") else "paw", text)
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


def _clear_corner_note(shot):
	"""Keep one corner of the floor empty: the real product is pasted there after drawing, never over the characters."""
	from .subject_overlay import pasted_references
	from .tuning import tune

	references = getattr(shot, "references", None) or []
	if not any(p["role"] == "product" for p in pasted_references(references, "Draw in scene")):
		return ""
	return f"Keep the bottom-{tune('drawn_product_corner')} corner of the floor clear and empty, with nothing on it. "


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


def _product_note(shot, project):
	"""Where the products are in a drawn scene: placed naturally in it, with no printed words."""
	from .subject_overlay import describe_colours

	labels = {
		(row.get("asset_version") if hasattr(row, "get") else getattr(row, "asset_version", None)):
		(row.get("label") if hasattr(row, "get") else getattr(row, "label", None))
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	colours = []
	for reference in getattr(shot, "references", None) or []:
		if _role_of(reference) != "product":
			continue
		version = reference.get("asset_version") if hasattr(reference, "get") else getattr(reference, "asset_version", None)
		if version in labels:
			colours.append(describe_colours(version).replace("mostly ", "") or "")
	if not colours:
		return ""
	count = len(colours)
	return (
		f"The {'products' if count > 1 else 'product'} from the product reference "
		f"({'; '.join(c for c in colours if c)}) {'sit' if count > 1 else 'sits'} naturally in the scene, resting on a "
		"low table, a counter or the floor to the side of the characters and away from their feet, at the size of a real "
		"household product, with only soft, unreadable label texture. "
	)


def _draw_prompt(shot, project):
	"""The keyframe prompt for "Draw in scene": the place, the action, and the mascots behaving like people.

	The reference board shows the characters on a plain background, so the place must be named first or the
	plain background becomes the scene; the posture sentence stops the model copying the seated reference pose.
	"""
	from .subject_overlay import usable_setting

	from .subject_overlay import describe_colours

	action = _first_actions(shot) or _scrub_for_drawing(getattr(shot, "image_prompt", None) or "")
	labels = {
		(row.get("asset_version") if hasattr(row, "get") else getattr(row, "asset_version", None)):
		(row.get("label") if hasattr(row, "get") else getattr(row, "label", None))
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	scales = {
		(row.get("asset_version") if hasattr(row, "get") else getattr(row, "asset_version", None)):
		float((row.get("scale") if hasattr(row, "get") else getattr(row, "scale", None)) or 1)
		for row in (project.get("references") or project.get("selected_media") or [])
	}
	briefs, sized = [], []
	for reference in getattr(shot, "references", None) or []:
		if _role_of(reference) != "character":
			continue
		version = reference.get("asset_version") if hasattr(reference, "get") else getattr(reference, "asset_version", None)
		if labels.get(version):
			colours = describe_colours(version)
			name = _describe_character(labels[version])
			briefs.append(name + (f" ({colours}; pale, light fur, never brown or tan)" if colours and "brown" not in colours.split(",")[0] else (f" ({colours})" if colours else "")))
			sized.append((name.split(",")[0], scales.get(version, 1.0)))
	cast = "; ".join(dict.fromkeys(briefs))
	size_rule = _size_sentence(sized)
	raw_roles = {
		frappe.scrub((r.get("reference_role") if hasattr(r, "get") else getattr(r, "reference_role", "")) or "")
		for r in getattr(shot, "references", None) or []
	}
	has_mascot, has_person = "character" in raw_roles, bool(raw_roles & {"person", "people", "talent"})
	if not has_mascot:
		return (
			f"{usable_setting(getattr(shot, 'setting_prompt', None))} {action}\n\n"
			+ ("The person shown in the reference photo is in the scene, keeping their own face and look, in a natural pose "
			   "doing what the scene describes, seen in a medium or wide shot. " if has_person else "")
			+ "Natural light, realistic composition."
		)
	product_note = _clear_corner_note(shot)
	return (
		f"{usable_setting(getattr(shot, 'setting_prompt', None))} {action}\n\n"
		"The characters are cartoon mascot characters who act exactly like human people: they stand upright on two legs, "
		"sit on chairs or the floor, walk, hold things in their paws and gesture the way people do, in a real, "
		"lived-in home with furniture around them"
		+ (f": {cast}" if cast else "")
		+ ". They look like the characters in the reference picture, but not in its seated pose. "
		+ size_rule
		+ product_note
		+ "Natural window light, realistic wide composition."
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
			from .subject_overlay import describe_colours

			# The video model prints words it is given onto objects, so the cast is named in plain English,
			# never by a label in the advertiser's language.
			name = _display_name(label, len(names) + 1)
			if name not in names:
				colours = describe_colours(field(reference, "asset_version"))
				names.append(f"{name} ({colours}; keep exactly these colours)" if colours else name)
	return names


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
			part.strip() for line in audio for part in line.lstrip()[len("Audio:"):].strip().rstrip(".").split(";")
			if part.strip() and not part.strip().casefold().startswith("music")
		]
		# A vocal sound inside a cue ("... Baby bear's giggling laughter.") is dropped with its sentence.
		cues = [
			" ".join(sentence for sentence in re.split(r"(?<=[.!])\s+", cue) if not VOCAL_SOUND.search(sentence))
			for cue in cues
		]
		cues = [cue.rstrip(". ") for cue in cues if cue]
		if not cues:
			# With nothing concrete to make, the model fills the soundtrack with music.
			cues = ["a soft paper rustle, a light tap, a gentle crinkle"]
		audio = [f"Audio: {_timed_events(cues, duration)}; silence between the sounds. {NO_VOICE_OR_MUSIC}"]
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
