"""Client for the planning language model (an OpenAI-compatible endpoint): video plans, shot revisions, titles and
captions, translation to English. Answers are validated; a model that is down is reported, never guessed around.
"""

import json
import re

import frappe
import requests
from frappe import _

from joymedia.services.planning.film_director import (
	balance_take_durations,
	build_director_instruction,
	close_the_film,
	is_product_film,
	name_story_beats,
	normalize_story_references,
	place_text,
	plan_problems,
	story_take_count,
)
from joymedia.services.planning.plan_parsing import (
	DEFAULT_MAX_MODEL_LEN,
	MIN_PLAN_COMPLETION_TOKENS,
	_completion_budget,
	_first_non_empty,
	_normalize_planner_plan,
	_normalized_motion_plan,
	_plan_shots,
	_request_plan,
	_rescale_motion_plan,
	_validate_video_plan,
)
from joymedia.services.runtime.endpoints import endpoint
from joymedia.services.scene.contract import PLANNING_RULES

PLAN_CUT_OFF = (
	"The previous JSON did not fit. Return a compact complete JSON plan: generation_prompt "
	"under 50 words, image_prompt under 30 words, exactly two motion actions of at most "
	"8 words each, and short state/title/caption fields. Do not omit shots or required fields."
)


def _planner_config():
	"""Return the configured planning capability, independent of its provider."""
	configured = endpoint("planner")
	return configured.base_url, configured.model, configured.timeout


# Kept for third-party integrations during the configuration-key migration.
# JoyMedia itself calls _planner_config exclusively.
_qwen_config = _planner_config
# Compatibility name for integrations that imported the old private helper.
_normalize_qwen_plan = _normalize_planner_plan


def generate_shot_revision(*, instruction, shot, product_name="", video_idea=""):
	"""Ask the configured planner to replace one canonical shot prompt."""
	base_url, model, timeout = _planner_config()
	current_prompt = str(shot.get("generation_prompt") or "").strip()
	current_image_prompt = str(shot.get("image_prompt") or "").strip()
	user_prompt = (
		"Revise exactly one cinematic commercial shot. Return only valid JSON. The revised scene description "
		"will provide a starting-frame image prompt for Flux and a separate motion-aware video prompt.\n\n"
		f"PRODUCT: {product_name}\n"
		f"VIDEO IDEA (source of truth): {video_idea}\n"
		f"USER INSTRUCTION: {instruction}\n\n"
		"CURRENT SHOT PROMPT:\n"
		f"{current_prompt}\n\n"
		"CURRENT IMAGE PROMPT:\n"
		f"{current_image_prompt}\n\n"
		"Return this shape:\n"
		'{"summary":"short explanation",'
		'"changes":[{"field":"Shot Prompt","detail":"..."}],'
		'"generation_prompt":"...","image_prompt":"..."}\n'
		"Return one complete replacement generation_prompt for video and one concise image_prompt describing only the starting frame. "
		"Keep both prompts faithful to the video idea and preserve details not changed by the instruction."
	)
	payload = {
		"model": model,
		"messages": [
			{"role": "system", "content": "You revise one video-generation shot prompt. Return JSON only."},
			{"role": "user", "content": user_prompt},
		],
		"response_format": {"type": "json_object"},
		"temperature": 0.2,
		"max_tokens": 1200,
	}
	try:
		response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=(10, timeout))
	except requests.Timeout:
		frappe.throw(
			_("The AI planner did not return a shot revision within {0} seconds.").format(int(timeout))
		)
	except requests.RequestException as exc:
		frappe.throw(_("The AI planner is unavailable at {0}: {1}").format(base_url, str(exc)))
	if not response.ok:
		frappe.throw(
			_("The AI planner request failed ({0}): {1}").format(response.status_code, response.text)
		)
	try:
		result = json.loads(response.json()["choices"][0]["message"]["content"])
	except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
		frappe.throw(_("The AI planner returned invalid shot revision JSON: {0}").format(str(exc)))
	if not isinstance(result, dict):
		frappe.throw(_("The AI planner returned an invalid shot revision."))
	generation_prompt = str(result.get("generation_prompt") or "").strip()
	if not generation_prompt:
		frappe.throw(_("The AI planner returned an empty generation_prompt for the shot revision."))
	result["generation_prompt"] = generation_prompt
	image_prompt = str(result.get("image_prompt") or result.get("image_generation_prompt") or "").strip()
	result["image_prompt"] = image_prompt or generation_prompt
	result["changes"] = result.get("changes") if isinstance(result.get("changes"), list) else []
	result["summary"] = str(result.get("summary") or "Shot changes are ready to review.").strip()
	return result


def improve_video_idea(
	*,
	current_idea: str,
	product_name: str = "",
	references: list[dict] | None = None,
	duration: float | None = None,
	delivery_preset: str | None = None,
) -> dict:
	"""Use the configured planner to elevate a raw idea into a structured concept."""
	try:
		base_url, model, timeout = _planner_config()
	except Exception:
		# Keep the user workflow usable when planning is not configured.
		fallback = _build_fallback_improved_idea(current_idea, product_name, references)
		return {"improved_idea": fallback}

	ref_lines = []
	for ref in references or []:
		key = ref.get("reference_key") or ref.get("asset_name") or ""
		role = ref.get("reference_role") or ref.get("asset_category") or "Reference"
		analysis = ref.get("analysis_summary") or ref.get("analysis") or ""
		if key:
			desc = f"- @{key} ({role})"
			if analysis:
				desc += f": {analysis[:120]}"
			ref_lines.append(desc)
	ref_text = "\n".join(ref_lines) if ref_lines else "None provided."

	user_prompt = (
		"You are an elite creative director for commercial AI video advertising (like Google Flow and Runway Gen-3).\n"
		"Enhance the creator's video idea into a vivid, cinematic, and compelling commercial video concept.\n\n"
		f"PRODUCT: {product_name or 'Commercial Showcase'}\n"
		f"CURRENT IDEA: {current_idea or 'Showcase the product in a stylish setting.'}\n"
		f"PLANNED DURATION: {duration or 15}s\n"
		f"ASPECT RATIO / FORMAT: {delivery_preset or 'Landscape 16:9'}\n"
		f"PROJECT INGREDIENTS / REFERENCES:\n{ref_text}\n\n"
		"RULES:\n"
		"1. Elevate narrative hook, lighting mood, camera motion, tactile material textures, and commercial elegance.\n"
		"2. Where appropriate, refer to ingredients using their exact @reference_key tag (e.g., @hero_shoe).\n"
		"3. Keep the prompt concise (2-4 sentences max), punchy, and production-ready for video synthesis.\n"
		"4. Write improved_idea in the same language as CURRENT IDEA (keep a Vietnamese idea in Vietnamese).\n"
		"5. Return ONLY valid JSON with shape:\n"
		'{"improved_idea": "The enhanced creative video concept..."}'
	)

	payload = {
		"model": model,
		"messages": [
			{
				"role": "system",
				"content": "You are a professional AI commercial video director. Return JSON only with key 'improved_idea'.",
			},
			{"role": "user", "content": user_prompt},
		],
		"response_format": {"type": "json_object"},
		"temperature": 0.7,
		"max_tokens": 600,
	}

	try:
		response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=(5, timeout))
		if response.ok:
			parsed = json.loads(response.json()["choices"][0]["message"]["content"])
			improved = str(parsed.get("improved_idea") or "").strip()
			if improved:
				return {"improved_idea": improved}
	except Exception as exc:
		frappe.logger("joymedia.planner").warning("Idea improvement failed, falling back: %s", exc)

	return {"improved_idea": _build_fallback_improved_idea(current_idea, product_name, references)}


# The planner was fine-tuned on examples titled "Biến thể TVC 12: …" and sometimes
# copies that numbering into titles.
TITLE_NUMBERING = re.compile(
	r"^\s*(?:(?:biến thể|bien the|variant|version|phiên bản|tvc|shot|cảnh|scene)[\s\w]*?\d+\s*(?:[:.\-–]\s*|$)"
	r"|(?:biến thể|bien the|variant)\b\s*[:.\-–]?\s*)",
	re.I,
)


def clean_title(title):
	"""A title without the planner's leaked example numbering."""
	return TITLE_NUMBERING.sub("", str(title or "").strip())[:80].strip()


def write_titles_and_captions(shots, video_idea):
	"""Title the film and its scenes, and caption them, from the scenes' final prompts.

	The fine-tuned planner titles scenes after its training examples (a diamond ring, a
	sports car) whatever the scene shows, so the words come from a separate request that
	reads only what each scene actually contains. Keeps the planner's words on failure.
	"""
	scenes = "\n".join(
		f"{index}. {str(shot.get('generation_prompt') or '')[:500]}"
		for index, shot in enumerate(shots, start=1)
	)
	request = (
		"You write the on-screen words of a short commercial video.\n"
		f"VIDEO IDEA (its language is the output language): {video_idea or 'none'}\n\n"
		f"SCENES, as described to the video model:\n{scenes}\n\n"
		'Return JSON: {"film_title": "...", "scenes": [{"title": "...", "caption": "..."}]} with one '
		"entry per scene, in order. film_title: at most 6 words. title: at most 6 words naming what the "
		"scene shows. caption: at most 6 words of on-screen text, a feeling or benefit the scene shows. "
		"Describe only what the scene text contains; never invent products, places, prices or brand "
		"names. Write everything in the language of the VIDEO IDEA (Vietnamese if it is Vietnamese)."
	)
	try:
		base_url, model, timeout = _planner_config()
		response = requests.post(
			f"{base_url}/chat/completions",
			json={
				"model": model,
				"messages": [
					{
						"role": "system",
						"content": "You write short, accurate on-screen text. Return JSON only.",
					},
					{"role": "user", "content": request},
				],
				"response_format": {"type": "json_object"},
				"temperature": 0.3,
				"max_tokens": 600,
			},
			timeout=(10, min(timeout, 180)),
		)
		response.raise_for_status()
		words = json.loads(response.json()["choices"][0]["message"]["content"])
	except Exception:
		frappe.logger("joymedia.planner").exception("Unable to write scene titles and captions")
		return {}
	entries = words.get("scenes") if isinstance(words, dict) else None
	if not isinstance(entries, list) or len(entries) != len(shots):
		return {}
	for shot, entry in zip(shots, entries, strict=False):
		entry = entry if isinstance(entry, dict) else {}
		title = clean_title(entry.get("title"))
		if title:
			name = str(shot.get("shot_name") or "")
			beat = name.split(":", 1)[0].strip() if ":" in name else ""
			shot["shot_name"] = f"{beat}: {title}" if beat else title
		shot["caption"] = clean_title(entry.get("caption"))[:60]
	return {"film_title": clean_title(words.get("film_title"))}


def _story_title(shots):
	"""The title of the climax scene (or the first scene), without its beat word."""
	names = [str(shot.get("shot_name") or "") for shot in shots]
	name = next((name for name in names if name.upper().startswith("CLIMAX")), names[0] if names else "")
	return clean_title(name.split(":", 1)[1] if ":" in name else name)


def default_captions(shots):
	"""Give captionless scenes their short title as on-screen text, except the last one.

	The planner often leaves captions empty; the title is already a short phrase in the
	language of the idea. The last scene stays clear for the closing title.
	"""
	for shot in shots[:-1]:
		if not str(shot.get("caption") or "").strip():
			name = str(shot.get("shot_name") or "")
			shot["caption"] = clean_title(name.split(":", 1)[1] if ":" in name else name)[:60]
	if len(shots) > 1:
		shots[-1]["caption"] = ""
	return shots


def _idea_for_planner(video_idea):
	"""Keep the marketer's exact brief authoritative while offering an English aid.

	Titles and captions must still come back in the idea's own language.
	"""
	idea = str(video_idea or "").strip()
	english = to_english(idea)
	if english == idea:
		return idea
	return (
		f"ORIGINAL MARKETER BRIEF (SOURCE OF TRUTH): {idea}\n"
		f"English translation for convenience only (do not replace the original brief): {english}\n"
		"Write film_title, shot_name titles and captions in the language of the original."
	)


def to_english(text):
	"""Translate a short creative description (e.g. a Vietnamese music mood) for the video model.

	English passes through unchanged; if the planner is unavailable the text is used as written.
	"""
	text = (text or "").strip()
	if not text or text.isascii():
		return text
	try:
		base_url, model, timeout = _planner_config()
		response = requests.post(
			f"{base_url}/chat/completions",
			json={
				"model": model,
				"messages": [
					{
						"role": "system",
						"content": "You translate short creative descriptions into natural English. Return JSON only.",
					},
					{
						"role": "user",
						"content": f'Translate into English: {text}\nReturn {{"english": "..."}}',
					},
				],
				"response_format": {"type": "json_object"},
				"temperature": 0,
				"max_tokens": 300,
			},
			timeout=(10, min(timeout, 120)),
		)
		response.raise_for_status()
		english = json.loads(response.json()["choices"][0]["message"]["content"]).get("english")
		return str(english).strip() or text
	except Exception:
		frappe.logger("joymedia.planner").exception("Unable to translate %r", text)
		return text


def _build_fallback_improved_idea(current_idea, product_name, references):
	base = (current_idea or "").strip()
	prod = product_name or "the product"
	ref_tags = [f"@{r.get('reference_key')}" for r in (references or []) if r.get("reference_key")]
	ref_str = f" highlighting {', '.join(ref_tags)}" if ref_tags else ""

	if not base:
		return f"A high-end cinematic commercial showcasing {prod}{ref_str} with dramatic studio lighting, macro texture passes, dynamic camera orbits, and an aspirational final brand resolve."
	if len(base) < 60:
		return f"{base.rstrip('.')}. Shot in crisp 4K with dramatic rim lighting, macro textural detail{ref_str}, seamless cinematic camera tracking, and a sleek modern aesthetic."
	return f"{base.rstrip('.')}. Enhanced with dynamic atmospheric depth, photorealistic textures{ref_str}, and fluid camera choreography."


def _example_reference_role(workflow_input_contract):
	for item in workflow_input_contract or []:
		role = str(item.get("role") or "").strip()
		if role:
			return role
	return "reference"


def _story_reference_roles(workflow_input_contract):
	"""Map semantic director slots to the selected workflow's declared input roles."""
	from joymedia.services.keyframes.reference_board import normalize_reference_role

	# Keep numbered product slots distinct while resolving aliases such as
	# ``character`` and ``product_reference``. Normalizing every role into one
	# dictionary key would let ``product_2`` overwrite the primary ``product``
	# slot, which changes the director's stable prompt contract.
	roles = {}
	for item in workflow_input_contract or []:
		declared = str(item.get("role") or "").strip()
		if not declared:
			continue
		semantic = normalize_reference_role(declared)
		roles.setdefault(semantic, declared)
		roles.setdefault(declared, declared)
	fallback = _example_reference_role(workflow_input_contract)
	return {
		"character": roles.get("person") or roles.get("character") or fallback,
		"product": roles.get("product") or fallback,
		"place": roles.get("environment") or fallback,
	}


def _review_product_plan(*, base_url, model, timeout, product_name, video_idea, plan):
	"""Run a strict second-pass brief check for character-led product commercials."""
	if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list):
		return plan
	messages = [
		{
			"role": "system",
			"content": (
				"You are a strict commercial-storyboard brief-compliance editor. "
				"The draft may contain serious semantic errors. Compare every shot to the user's brief; "
				"rewrite mismatching action, product, or setting instead of preserving it. Return only JSON."
			),
		},
		{
			"role": "user",
			"content": (
				"USER VIDEO IDEA (source of truth):\n"
				f"{_idea_for_planner(video_idea)}\n\n"
				f"PRODUCT NAME: {product_name}\n\n"
				"DRAFT PLAN:\n"
				+ json.dumps(plan, ensure_ascii=False)
				+ "\n\nCOMPLIANCE REVIEW AND REWRITE RULES:\n"
				"- The user idea, not the draft, decides what the person does and where the scene occurs.\n"
				"- Keep the requested product, requested action, and requested setting in every relevant shot.\n"
				"- Remove any invented activity, genre, location, or action that conflicts with the idea.\n"
				"- Product reference images establish the object's appearance; never turn a depicted picture into the setting.\n"
				"- Keep shot count, shot numbers, durations, reference keys, and usage roles unchanged.\n"
				"- Rewrite every generation_prompt in English, with one clear continuous action and camera move.\n"
				"- Return the full plan JSON with the same fields; no analysis or extra fields."
			),
		},
	]
	payload = {
		"model": model,
		"messages": messages,
		"response_format": {"type": "json_object"},
		"temperature": 0,
		"max_tokens": 3000,
	}
	payload["max_tokens"] = _completion_budget(base_url, payload)
	reviewed = _request_plan(base_url, payload, timeout)
	if not isinstance(reviewed, dict) or not isinstance(reviewed.get("shots"), list):
		return plan
	if len(reviewed["shots"]) != len(plan["shots"]):
		return plan
	return reviewed


def generate_video_plan(
	*,
	product_name: str,
	video_idea: str,
	total_video_duration: float,
	target_fps: float,
	shot_count: int | None = None,
	reference_images: list[dict] | None = None,
	reference_media: list[dict] | None = None,
	generation_mode: str = "Multi-shot",
	global_instructions: str | None = None,
	format_preset: str | None = None,
	workflow_input_contract: list[dict] | None = None,
	continuation_context: dict | None = None,
	story_film: bool = False,
) -> dict:
	"""Create one structured storyboard from the project prompt and selected references.

	Reference media is planning context only. Actual workflow inputs are resolved by
	JoyMedia after planning so Asset/Asset Version stays separate from Generation Input.
	"""
	from joymedia.services.project.modes import normalize_generation_mode

	generation_mode = normalize_generation_mode(generation_mode)
	if generation_mode not in ("Multi-shot", "Continuous"):
		frappe.throw(_("Select Continuous or Multi-shot generation mode."))
	base_url, model, timeout = _planner_config()
	story_reference_role = _example_reference_role(workflow_input_contract)
	story_reference_roles = _story_reference_roles(workflow_input_contract)
	story_reference_contexts = reference_media
	workflow_input_contract_for_prompt = workflow_input_contract

	instruction = """
You are the creative planner for JoyMedia product videos.
Understand the complete video idea first, then divide it into a coherent sequence
of creative shots. For every shot, return a scene-composition image_prompt,
an action-focused generation_prompt, and a seconds-based motion_plan. The
image prompt describes the intended starting frame only. The video prompt describes
one continuous motion from that starting frame. Keep generation_prompt as a concise
creative summary for backward-compatible clients.

Project reference media are named ingredients/context. Use their reference_key when
a shot intentionally uses one. Never emit Asset Version IDs or image indexes.
""".strip()
	if story_film:
		instruction = build_director_instruction(
			story_reference_contexts, story_reference_role, total_video_duration, story_reference_roles
		)
		# The director roster replaces the generic reference, image and contract lists.
		reference_images = None
		reference_media = None
		workflow_input_contract_for_prompt = None

	if workflow_input_contract_for_prompt:
		instruction += (
			"\n\nAVAILABLE INPUT ROLES FOR THIS WORKFLOW:\n"
			+ json.dumps(workflow_input_contract, ensure_ascii=False, indent=2)
			+ "\nUse only these roles. Respect accepted_media_type, required, and allow_multiple."
		)
	if format_preset:
		instruction += f"\n\nOUTPUT FORMAT:\n{format_preset}. Frame each shot appropriately for this format."
	if global_instructions:
		instruction += f"\n\nGLOBAL INSTRUCTIONS FOR EVERY SHOT:\n{global_instructions}"
	if story_film:
		pass  # Takes are rendered with references, not first-frame chaining.
	elif generation_mode == "Continuous":
		instruction += (
			"\n\nGENERATION MODE: CONTINUOUS\n"
			"The first shot starts from a selected image. Later shots continue from the previous generated last frame. "
			"Plan motion that can continue naturally while preserving product identity and scene state.\n"
			"Plan action in seconds. Major action should finish in the first 85-90% of the shot; "
			"use the ending for a natural motion, pose, or camera handoff."
		)
	else:
		instruction += (
			"\n\nGENERATION MODE: MULTI-SHOT\n"
			"Shots are generated from explicitly resolved keyframes/references. Keep boundaries coherent.\n"
			"Plan action in seconds and make each boundary a deliberate, compatible handoff."
		)
	if continuation_context:
		previous_prompt = str(continuation_context.get("previous_prompt") or "").strip()
		requested_instruction = str(continuation_context.get("instruction") or "").strip()
		instruction += (
			"\n\nAPPEND EXISTING VIDEO\n"
			f"The existing video ends with this previous shot prompt:\n{previous_prompt}\n\n"
			f"Plan ONLY the next {total_video_duration} seconds. Do not restart the advertisement.\n"
			"The first new shot begins from the previous generated shot's exact last frame.\n"
			"Preserve product identity, product appearance and proportions, environment, lighting logic, spatial state, "
			"subject position, movement direction and camera continuity.\n\n"
			"USER NEXT-SCENE INSTRUCTION:\n"
			f"{requested_instruction or 'No explicit instruction. Choose the most natural commercially compelling continuation yourself.'}"
		)

	example_role = story_reference_role
	if story_film and is_product_film(story_reference_contexts):
		example_references = (
			f'{{"reference_key":"<character key>","usage_role":"{story_reference_roles["character"]}"}},'
			f'{{"reference_key":"<product key>","usage_role":"{story_reference_roles["product"]}"}}'
		)
	elif story_film:
		example_references = (
			f'{{"reference_key":"<character key>","usage_role":"{story_reference_roles["character"]}"}},'
			f'{{"reference_key":"<place key>","usage_role":"{story_reference_roles["place"]}"}}'
		)
	else:
		example_references = f'{{"reference_key":"hero_product","usage_role":"{example_role}"}}'
	response_shape = (
		'{"film_title":"...","shots":[{"shot_number":1,"shot_name":"...",'
		'"duration_seconds":5,"generation_prompt":"...","image_prompt":"...",'
		'"start_state":"...","end_state":"...",'
		'"handoff_type":"motion_continuation","continuity_mode":"New Scene or Continue",'
		'"motion_plan":{"actions":[{"start":0,"end":4,"action":"..."},{"start":4,"end":5,"action":"..."}]},"caption":"...",'
		f'"references":[{example_references}]}}]}}'
	)
	take_count = story_take_count(total_video_duration, story_reference_contexts) if story_film else None
	user_prompt = (
		f"{instruction}\n\n"
		f"PRODUCT NAME\n{product_name}\n\n"
		f"VIDEO IDEA\n{_idea_for_planner(video_idea)}\n\n"
		f"TOTAL VIDEO DURATION: {total_video_duration} seconds\n"
		f"TARGET FPS: {target_fps}\n"
		f"SHOT COUNT GUIDANCE: {shot_count if shot_count is not None else f'Exactly {take_count} takes, one per place.' if take_count else 'Choose the appropriate number of creative shots; do not use model frame capacity to choose it.'}\n\n"
		+ (
			f"Return exactly {shot_count} shots. "
			if shot_count is not None
			else f"Return exactly {take_count} takes as shots. "
			if take_count
			else "Choose a coherent storyboard structure, normally between 1 and 8 shots. "
		)
		+ "Organize the shots into a coherent narrative progression.\n\n"
		+ PLANNING_RULES
		+ "\n"
		+ "IMPORTANT OUTPUT RULES:\n"
		"- Every shot MUST contain a positive integer shot_number.\n"
		"- Every shot MUST contain one non-empty generation_prompt.\n"
		"- Every shot MUST contain non-empty image_prompt and generation_prompt.\n"
		"- motion_plan.actions must be chronological approximate intervals in seconds within duration_seconds.\n"
		"- Use motion_continuation, pose_transition, or camera_transition for a non-final handoff; use ending for the final shot.\n"
		"- The final shot must complete the film: reach its final end_state before its duration ends, settle into a held composition, and contain no new transition, setup, or action after that state.\n"
		"- Every shot MUST contain a positive duration_seconds value.\n"
		"- Never return null or empty generation_prompt values.\n"
		"- References must use only supplied reference_key values and semantic usage_role values.\n"
		"- film_title is a short catchy title for the video (at most 6 words) in the same language as the "
		"VIDEO IDEA; Vietnamese if the idea is written in Vietnamese.\n"
		"- Write every generation_prompt in English, even when the VIDEO IDEA is in Vietnamese or another language.\n"
		"- Write each shot_name title in the language of the VIDEO IDEA.\n"
		"- caption is the short on-screen text for that shot (at most 6 words, in the language of the "
		"VIDEO IDEA): a feeling or benefit the shot shows, never invented facts, prices or brand names. "
		"Leave it empty for the last shot.\n\n"
		"Return only valid JSON with this shape:\n"
		f"{response_shape}"
	)

	if reference_media:
		user_prompt += "\n\nSELECTED PROJECT REFERENCES / INGREDIENTS\n"
		for index, item in enumerate(reference_media, start=1):
			line = (
				f"\nREFERENCE {index}: key={item.get('reference_key')}, "
				f"role={item.get('reference_role') or 'General'}, label={item.get('label') or ''}, "
				f"name={item.get('asset_name') or 'Untitled'}, "
				f"type={item.get('media_type') or 'Unknown'}, category={item.get('asset_category') or 'Other'}"
			)
			analysis = item.get("analysis")
			if analysis:
				line += "\nANALYSIS: " + json.dumps(analysis, ensure_ascii=False)
			user_prompt += line
		user_prompt += (
			"\nUse reference analysis when provided. For media without analysis, use only the supplied name/type/category; "
			"do not claim to have inspected its pixels, audio or frames."
		)

	if reference_images:
		user_prompt += (
			"\n\nGENERATION IMAGE REFERENCES\n"
			+ f"JoyMedia supplied {len(reference_images)} selected image references in order. "
			"Do not output image indexes."
		)
		for image in reference_images:
			user_prompt += (
				f"\nIMAGE {image['index']}: key={image.get('reference_key') or ''}, "
				f"name={image['asset_name']}"
			)
		if generation_mode == "Multi-shot" and shot_count == len(reference_images):
			user_prompt += (
				"\nThere is one independent image for each Shot. Use the images in order: "
				"Shot 1 uses IMAGE 1, Shot 2 uses IMAGE 2, and so on. "
				"Each generation_prompt must describe the actual scene shown by its assigned image "
				"using the supplied reference analysis; never swap rooms, amenities, or locations between images."
			)

	request_payload = {
		"model": model,
		"messages": [
			{
				"role": "system",
				"content": "You produce structured JSON video plans. Do not include markdown fences or commentary.",
			},
			{"role": "user", "content": user_prompt},
		],
		"response_format": {"type": "json_object"},
		"temperature": 0.4 if story_film else 0.2,
		"max_tokens": 3000,
	}
	request_payload["max_tokens"] = _completion_budget(base_url, request_payload)

	result = _request_plan(base_url, request_payload, timeout)
	# Product films describe their settings in words, so there is no place photo to check.
	places = (
		{context.get("reference_key"): place_text(context) for context in story_reference_contexts or []}
		if story_film and not is_product_film(story_reference_contexts)
		else None
	)

	def problems_of(plan):
		if plan is None:
			return [PLAN_CUT_OFF]
		return plan_problems(_plan_shots(plan), take_count, places) if take_count else []

	problems = problems_of(result)
	if problems:
		# The fine-tuned planner tends to return its habitual 3 shots, repeat one prompt or
		# drift out of a take's place; correct it once. The retry is a fresh request with the
		# corrections: replaying its previous answer would overflow the planner's context.
		corrections = "\n".join(f"- {problem}" for problem in problems)
		if take_count:
			corrections += (
				f"\n- Return exactly {take_count} takes following the STORY ARC, "
				f"durations adding up to {total_video_duration} seconds."
			)
		system, user = request_payload["messages"][:2]
		retry_payload = {
			**request_payload,
			"messages": [
				system,
				{**user, "content": f"{user['content']}\n\nCORRECTIONS TO APPLY:\n{corrections}"},
			],
		}
		retry_payload["max_tokens"] = _completion_budget(base_url, retry_payload)
		retry_result = _request_plan(base_url, retry_payload, timeout)
		if retry_result is not None:
			retry_problems = problems_of(retry_result)
			if not retry_problems or len(retry_problems) < len(problems):
				result = retry_result
	if result is None:
		frappe.throw(_("The AI director's answer was cut off. Please try again."))
	if story_film and is_product_film(story_reference_contexts):
		result = _review_product_plan(
			base_url=base_url,
			model=model,
			timeout=timeout,
			product_name=product_name,
			video_idea=video_idea,
			plan=result,
		)

	if story_film and isinstance(result, dict) and isinstance(result.get("shots"), list):
		normalize_story_references(
			result["shots"], story_reference_contexts, story_reference_role, story_reference_roles
		)
		from joymedia.services.planning.film_director import enforce_requested_product_presentation

		enforce_requested_product_presentation(result["shots"], video_idea, story_reference_contexts)
		from joymedia.services.planning.film_director import enforce_explicit_product_brief

		enforce_explicit_product_brief(result["shots"], video_idea)

	film_title = clean_title(result.get("film_title")) if isinstance(result, dict) else ""
	result = _normalize_planner_plan(
		result,
		reference_image_count=len(reference_images or []),
		generation_mode=generation_mode,
		reference_images=reference_images,
		workflow_input_contract=workflow_input_contract,
		total_video_duration=total_video_duration,
	)
	_validate_video_plan(
		result,
		reference_image_count=len(reference_images or []),
		shot_count=shot_count,
		generation_mode=generation_mode,
		workflow_input_contract=workflow_input_contract,
		total_video_duration=total_video_duration,
	)
	if story_film:
		result["shots"] = balance_take_durations(name_story_beats(result["shots"]), total_video_duration)
	# Every request returns a complete playable film, including appended scenes.
	# The final scene therefore always closes the current film rather than
	# implying another transition beyond the planned duration.
	close_the_film(result["shots"])
	words = write_titles_and_captions(result["shots"], video_idea)
	if words.get("film_title"):
		film_title = words["film_title"]
	default_captions(result["shots"])
	# A title that was only the planner's numbering (or one word left of it) falls back
	# to the climax's title.
	if len(film_title.split()) < 2:
		film_title = _story_title(result["shots"]) or film_title
	if film_title:
		result["film_title"] = film_title
	return result
