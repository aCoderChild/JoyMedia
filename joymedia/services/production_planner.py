"""Production planning: turn creative beats into production shots.

An imported storyboard describes what the advertiser wants to *see* (creative beats). The
generation models need something different: a concrete starting frame for the image model
and a motion description for the video model, plus the references each frame depends on.
This stage derives those from each beat with the planner model. The advertiser's own words
(timing, voice-over, on-screen text, claims, the source rows) are never rewritten; only
prompts, continuity and reference assignments are proposed, for the user to review.
"""

import json

import frappe
import requests
from frappe import _

from joymedia.services.qwen_client import _normalized_motion_plan, _qwen_config

MAX_PROMPT_CHARS = 700
MAX_IMAGE_WORDS = 70
SYSTEM_PROMPT = (
	"You are a production planner for AI-generated video advertisements. You convert one creative beat "
	"into one production shot for an image model (the starting frame) and an image-to-video model (the "
	"motion). Return JSON only."
)


def plan_production_shot(project, shot, *, previous_end_state="", references=None):
	"""Ask the planner for one shot's production plan and return it validated (nothing is saved)."""
	references = references if references is not None else project_reference_options(project)
	beat = creative_beat(project, shot)
	prompt = build_planning_prompt(project, shot, beat, references, previous_end_state)
	raw = _ask_planner(prompt)
	if len(str((raw or {}).get("image_prompt") or "").split()) > MAX_IMAGE_WORDS:
		# One corrective retry: the image prompt must describe a single frame, not the whole action.
		raw = _ask_planner(
			prompt + f"\nYour previous image_prompt was too long. Rewrite it as one still frame of at most {MAX_IMAGE_WORDS - 10} words."
		)
	plan = normalize_production_shot(
		raw,
		reference_keys={reference["key"] for reference in references},
		duration=float(shot.duration_seconds or 0),
		is_first=int(shot.shot_number or 0) <= 1,
	)
	if not plan["video_prompt"].isascii():
		# A video prompt that copied the beat's language, or mixed it with a translation, is not usable: the
		# movement of the beat's English translation replaces it.
		plan["video_prompt"] = motion_only(project, beat["summary"], references) or beat["summary"]
		plan["motion_plan"] = {"actions": [{"start": 0, "end": float(shot.duration_seconds or 1), "action": plan["video_prompt"]}]}
		plan["notes"].append("The planner did not answer in English, so the video prompt is the beat's movements.")
	for key in ("image_prompt", "setting_prompt", "sound_effects"):
		# The models read English; a planner answer that copied the beat's own language is translated.
		plan[key] = translate(plan.get(key), project)
	plan["audio"] = audio_direction(project, beat, plan.get("sound_effects"))
	plan["reference_keys"], added_notes = ground_reference_keys(project, beat, plan["reference_keys"], references)
	plan["notes"].extend(added_notes)
	coverage, missing = beat_coverage(beat["summary"], plan["image_prompt"], plan["video_prompt"])
	plan["coverage"] = round(coverage, 2)
	plan["held_back"] = False
	if coverage < REVIEW_COVERAGE and missing:
		plan["notes"].append(f"May omit from the beat: {', '.join(missing[:12])}.")
	if coverage < MIN_COVERAGE and beat["summary"]:
		# A plan that dropped much of the beat must not replace the advertiser's description. The beat's own
		# English wording becomes the video prompt, so the model never receives the raw foreign-language text.
		# The video starts from a first frame that already shows the place, lighting and objects, so only the
		# movement is kept; a description of a different place or light would pull the video away from it.
		movement = motion_only(project, beat["summary"], references) or beat["summary"]
		plan["video_prompt"] = movement
		plan["motion_plan"] = {"actions": [{"start": 0, "end": float(shot.duration_seconds or 1), "action": movement}]}
		plan["notes"].append("Plan covers too little of the beat, so the beat's own wording, reduced to its movements, is used as the video prompt.")
	return plan


def motion_only(project, text, references):
	"""The beat's actions and camera moves only, in English, without place, lighting or objects that do not move."""
	cast = ", ".join(r["label"] for r in references or [] if r.get("role") in ("Character", "Person"))
	prompt = (
		"Rewrite this storyboard beat as ONLY what moves: the actions of the characters and the camera, in time "
		"order, in at most 60 words of English. Remove every description of the place, lighting, time of day, "
		"colours and objects that are not moving, and every quantity, name or word that would print as text on an "
		f"object. Characters: {cast or 'as in the beat'}; every bear, mother or "
		f"baby named is one of them.\nBEAT: {text}\nReturn {{\"motion\": \"...\"}}"
	)
	raw = _ask_planner(prompt, system="You rewrite storyboard beats faithfully. Return JSON only.", max_tokens=300)
	return " ".join(str((raw or {}).get("motion") or "").split())


def project_reference_options(project):
	"""Visual project references the planner may assign to a shot."""
	options = []
	for row in project.selected_media or []:
		if not row.reference_key or not row.asset_version:
			continue
		asset = frappe.db.get_value("Asset Version", row.asset_version, "media_asset")
		if not asset or frappe.db.get_value("Media Asset", asset, "media_type") != "Image":
			continue
		option = {"key": row.reference_key, "label": row.label or row.reference_key, "role": row.reference_role or "General"}
		try:
			analysis = frappe.parse_json(frappe.db.get_value("Asset Version", row.asset_version, "analysis_json") or "{}")
		except (TypeError, ValueError):
			analysis = {}
		# What the picture actually shows (pose, framing) lets the prompt agree with it.
		if isinstance(analysis, dict) and analysis.get("description"):
			option["description"] = " ".join(str(analysis["description"]).split())[:200]
		options.append(option)
	return options


def creative_beat(project, shot):
	"""The advertiser's own description of the beat, verbatim; imported rows when available."""
	source = {}
	try:
		scenes = (frappe.parse_json(project.storyboard_source_json or "{}") or {}).get("selected_demo", {}).get("scenes", [])
	except (TypeError, ValueError):
		scenes = []
	for scene in scenes:
		if scene.get("beat_name") == (shot.storyboard_beat or shot.shot_name):
			source = scene
			break
	text = {
		"camera": source.get("visual_camera") or "",
		"action": source.get("action") or "",
		"voice_over": source.get("voice_over") or shot.voice_over or "",
		"on_screen_text": source.get("on_screen_text") or shot.caption or "",
		"audio": source.get("audio_cues") or shot.audio_cues or "",
	}
	if not (text["camera"] or text["action"]):
		text["action"] = shot.generation_prompt or ""
	# The models read English; the advertiser's original wording stays on the shot and in the source.
	text["raw"] = " ".join(filter(None, (text["camera"], text["action"])))
	text["camera"], text["action"] = translate(text["camera"], project), translate(text["action"], project)
	text["summary"] = " ".join(filter(None, (text["camera"], text["action"]))).strip()
	return text


def translate(text, project):
	"""Faithful English translation, given what the advertisement is about.

	Without context the planner model mistranslates product words ("giay" as leaves, "rut giay" as drawing).
	"""
	text = str(text or "").strip()
	if not text or text.isascii():
		return text
	references = ", ".join(row.label for row in project.selected_media or [] if row.label)
	context = (
		f"This is a storyboard for an advertisement for: {project.product_name or project.project_name}. "
		f"Characters and products shown: {references or 'not specified'}. Product words refer to the advertised "
		"product (for example 'giấy' means its tissue paper sheets); any bear, mother or baby in the text is the "
		"listed character, and 'tay' (hand) is that character's own paw."
	)
	prompt = (
		f"{context}\nTranslate this storyboard text into English. Be literal and complete; do not add, remove or "
		f"change any detail.\nTEXT: {text}\nReturn {{\"english\": \"...\"}}"
	)
	for attempt in range(2):
		raw = _ask_planner(
			prompt + ("\nThe answer must be written in English only, not in the original language." if attempt else ""),
			system="You translate storyboard text faithfully. Return JSON only.", max_tokens=600,
		)
		english = str((raw or {}).get("english") or "").strip()
		if english and english.isascii():
			return english
	return text


def audio_direction(project, beat, foley=None):
	"""The beat's sound direction as the H3 workflow's own `Audio:` line.

	The H3 workflow generates its soundtrack (effects, music) from the prompt, in the form its own sample
	prompt uses: an `Audio:` line. A planned video prompt replaces the storyboard text, so without this the
	scene's sound effects would silently disappear. Voice-over is recorded separately and is not included.
	"""
	from joymedia.services.audio_plan import parse_audio_cues

	parts = [
		f"{'sound effects' if role == 'SFX' else 'music'}: {translate(text, project)}"
		for role, text in parse_audio_cues(beat.get("audio"))
	]
	if not parts and foley:
		# The beat names no sound: use the planner's description of the physical sounds of the action.
		parts = [f"sound effects: {foley.rstrip('. ')}"]
	return f"Audio: {'; '.join(parts)}." if parts else ""


def build_planning_prompt(project, shot, beat, references, previous_end_state):
	aspect = "portrait 9:16" if (project.delivery_height or 0) > (project.delivery_width or 0) else "landscape"
	lines = [
		f"PROJECT: {project.product_name or project.project_name}. Format: {aspect}.",
		f"BRIEF: {' '.join(str(project.video_idea or '').split())[:300]}",
		"AVAILABLE REFERENCES (use only these keys):",
		*(
			f"- {ref['key']}: {ref['label']} ({ref['role']})" + (f". It shows: {ref['description']}" if ref.get("description") else "")
			for ref in references
		),
	] if references else [
		f"PROJECT: {project.product_name or project.project_name}. Format: {aspect}.",
		f"BRIEF: {' '.join(str(project.video_idea or '').split())[:300]}",
		"AVAILABLE REFERENCES: none.",
	]
	lines += [
		"",
		f"CREATIVE BEAT (must be preserved): {shot.storyboard_beat or shot.shot_name}, "
		f"{float(shot.duration_seconds or 0):g} seconds.",
		f"Camera and visuals: {beat['camera'] or '-'}",
		f"Action: {beat['action'] or '-'}",
		f"Voice-over (recorded separately, informational): {beat['voice_over'][:160] or '-'}",
		f"On-screen text (added in editing; never draw text in the image): {beat['on_screen_text'][:120] or '-'}",
		f"PREVIOUS SHOT ENDS WITH: {previous_end_state or 'nothing (this is the first shot)'}",
		"",
		"RULES (write everything in English, whatever language the beat uses; describe each reference by what it "
		"is in plain words, for example 'the mascot' or 'the tissue pack', never by its file label or "
		"brand name, and never copy the beat's wording or the role in brackets):",
		f"- The advertised product is: {project.product_name or project.project_name}. Generic words in the beat "
		"for it (paper, bottle, bag...) mean this product; never substitute a different product.",
		"- image_prompt: English, at most 60 words. Describe only the first frame: subjects, setting, framing, "
		"lighting. Include only what must appear. No text, captions or logos.",
		"- setting_prompt: English, at most 30 words. Only the place, light and camera framing of the first frame: "
		"no character, animal, hand, product, object in action or text.",
		"- sound_effects: English, at most 15 words: the physical, non-vocal sounds this action makes (rustling, "
		"tearing, a thud, pouring). Never speech, laughter, singing or music.",
		"- Never write quantities, prices, product names or any words that would appear as printed text on an "
		"object (for example a number of packs): the image and video models would draw them as letters.",
		"- video_prompt: English, at most 80 words. What moves and how the camera moves, in time order, as one "
		"continuous shot. Keep every action the beat requires; invent no claims or extra characters.",
		"- image_prompt is ONE still frame, never a sequence of events. When a reference shows a pose, keep the "
		"character's pose in the prompt consistent with it.",
		"- Name a character only as the same subject its reference shows (for example 'the mascot'); never use a "
		"generic animal or person word such as 'bear cub' or 'woman', which makes the video model invent a "
		"different one.",
		"- The listed Character references are the whole cast, and each is a different individual. A mother, mom or "
		"mama in the beat is the listed mother; a baby, kid, child or cub is the listed kid; a hand, arm or paw is "
		"that character's own (never a separate person's, never a different animal). Keep every action in the beat, "
		"even those before or after the main action.",
		"- reference_keys: include the key of EVERY listed character or product that is visible in the first frame "
		"(the advertised product's pack whenever the product itself is shown). Empty only if none is visible.",
		'- continuity_mode: "Continue" only if this beat continues the same scene, subject and setting from the '
		'previous shot; otherwise "New Scene".',
		'- needs_editing: if the beat needs several cuts, locations or a split-screen that one continuous clip '
		'cannot show, give a short reason and plan the single most important moment; else "".',
		"- motion_plan: actions with start and end in seconds covering the duration.",
		"",
		'EXAMPLE of the style: image_prompt "Extreme close-up of the mascot sitting at a wooden '
		'table, holding a glass of orange juice, soft daylight, shallow depth of field." video_prompt "The mascot '
		'tips the glass and juice spills across the table; the camera slowly pushes in as the mascot gasps."',
		"",
		'Return {"image_prompt":"","setting_prompt":"","sound_effects":"","video_prompt":"","reference_keys":[],"continuity_mode":"New Scene",'
		'"start_state":"","end_state":"","motion_plan":{"actions":[{"start":0,"end":0,"action":""}]},'
		'"needs_editing":""}',
	]
	return "\n".join(lines)


STOPWORDS = frozenset(
	"this that with from into onto over under then than they them their there where while which will would "
	"each every some very much more most only just also have has had been being were what when who whom "
	"about after before above below between during through across along behind beside around against "
	"angle camera shot shots close closeup extreme medium wide macro super lighting light soft focus depth field "
	"smooth gentle slowly slow frame view scene style look feel image video".split()
)
MIN_COVERAGE = 0.5
REVIEW_COVERAGE = 0.85


def _words(text, minimum=4):
	"""Lower-case ASCII words (accents folded, so 'giấy' and 'giay' match) of at least `minimum` letters."""
	import re
	import unicodedata

	folded = unicodedata.normalize("NFKD", str(text or "").replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
	return set(re.findall(r"[a-z]{%d,}" % minimum, folded.lower()))


# Words in a reference's label that say what kind of image it is, not what it shows.
LABEL_FILLER = frozenset("mascot character person model image photo picture pack package box background room reference".split())


def ground_reference_keys(project, beat, keys, references):
	"""Add the references a beat names in its own words, which the planner's guess can miss.

	- A product reference is added when the beat mentions the advertised product (matched on the
	  product's name, not on the model's guess).
	- Any other reference is added when the beat uses a distinctive word of the reference's own label
	  (a reference labelled 'Gau Shera mascot' for a beat about 'gấu').
	Words that belong to the advertised product are not distinctive enough to pull in a character.
	Returns the keys and notes explaining what was added.
	"""
	beat_text = " ".join((beat.get("raw", ""), beat.get("camera", ""), beat.get("action", "")))
	beat_words, beat_short = _words(beat_text), _words(beat_text, 3)
	product_words = _words(project.product_name) - _words(
		" ".join(r["label"] for r in references if r["role"] != "Product")
	)
	product_brand = _words(project.product_name, 3)
	added, notes = [], []
	for reference in references:
		if reference["key"] in keys:
			continue
		if reference["role"] == "Product":
			hit = product_words & beat_words
			reason = "the beat mentions the product"
		else:
			distinctive = _words(reference["label"], 3) - LABEL_FILLER - product_brand
			hit = distinctive & beat_short
			reason = "the beat mentions it"
		if hit:
			added.append(reference["key"])
			notes.append(f"Added reference '{reference['label']}': {reason}.")
	return keys + added, notes


def beat_coverage(beat_text, *texts):
	"""Fraction of the beat's content words (matched by 4-letter stem) that the plan still mentions.

	A rewrite that drops a required character, object or action scores low, so it can be held back for a
	person to review instead of silently replacing the advertiser's description.
	"""
	import re

	def stems(text):
		return {w[:4] for w in re.findall(r"[a-z]{4,}", str(text).lower()) if w not in STOPWORDS}

	wanted = stems(beat_text)
	if not wanted:
		return 1.0, []
	have = stems(" ".join(texts))
	missing = sorted(w for w in wanted if w not in have)
	return 1 - len(missing) / len(wanted), missing


def normalize_production_shot(raw, *, reference_keys, duration, is_first):
	"""Validate the planner's answer. Unknown references are dropped and reported; the rest must be usable."""
	if not isinstance(raw, dict):
		frappe.throw(_("The planner returned an invalid production plan."))
	image_prompt = " ".join(str(raw.get("image_prompt") or "").split())[:MAX_PROMPT_CHARS]
	video_prompt = " ".join(str(raw.get("video_prompt") or "").split())[:MAX_PROMPT_CHARS]
	if not image_prompt or not video_prompt:
		frappe.throw(_("The planner did not return both an image prompt and a video prompt."))
	if len(image_prompt.split()) > MAX_IMAGE_WORDS:
		frappe.throw(_("The planner's image prompt describes more than one frame; review this scene by hand."))
	keys, notes = [], []
	for key in raw.get("reference_keys") if isinstance(raw.get("reference_keys"), list) else []:
		key = str(key).strip()
		if key in reference_keys and key not in keys:
			keys.append(key)
		elif key:
			notes.append(f"Ignored unknown reference '{key}'.")
	mode = "Continue" if str(raw.get("continuity_mode") or "").strip().casefold() == "continue" else "New Scene"
	motion = _normalized_motion_plan(raw.get("motion_plan"), duration, video_prompt)
	if any(a["end"] <= a["start"] or a["start"] < 0 or a["end"] > duration + 0.01 for a in motion["actions"]):
		motion = {"actions": [{"start": 0, "end": duration, "action": video_prompt}]}
		notes.append("Motion timing was invalid and was replaced with one action.")
	needs_editing = " ".join(str(raw.get("needs_editing") or "").split())
	if needs_editing:
		notes.append(f"Needs editing: {needs_editing}")
	return {
		"image_prompt": image_prompt, "video_prompt": video_prompt, "reference_keys": keys,
		"setting_prompt": " ".join(str(raw.get("setting_prompt") or "").split())[:300],
		"sound_effects": " ".join(str(raw.get("sound_effects") or "").split())[:160],
		"continuity_mode": "New Scene" if is_first else mode,
		"start_state": " ".join(str(raw.get("start_state") or "").split())[:300],
		"end_state": " ".join(str(raw.get("end_state") or "").split())[:300],
		"motion_plan": motion, "notes": notes,
	}


def apply_production_shot(project, shot, plan):
	"""Write the planned prompts, continuity and references onto the shot; timing and copy are untouched."""
	from joymedia.api.storyboard import _assign_shot_references

	shot.image_prompt = plan["image_prompt"]
	shot.setting_prompt = plan.get("setting_prompt", "")
	shot.generation_prompt = plan["video_prompt"] + (f"\n\n{plan['audio']}" if plan.get("audio") else "")
	shot.motion_plan_json = frappe.as_json(plan["motion_plan"])
	shot.start_state, shot.end_state = plan["start_state"], plan["end_state"]
	shot.continuity_mode = plan["continuity_mode"]
	shot.planner_notes = "\n".join(plan["notes"])
	shot.save(ignore_permissions=True)
	_assign_shot_references(project, {shot.name: plan["reference_keys"]})


def request_seed(*parts):
	import hashlib

	return int(hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:8], 16)


CACHE_SECONDS = 7 * 24 * 3600


def _ask_planner(prompt, *, system=SYSTEM_PROMPT, max_tokens=900, refresh=False):
	"""Ask the planner; an identical request returns the stored answer.

	The model is not deterministic even at temperature 0, so re-planning an unchanged beat would give a
	different plan each time. Answers are cached in Frappe's cache keyed by the exact request; pass
	refresh=True (or change the beat, references or brief) for a fresh one.
	"""
	cache_key = f"joymedia_planner:{request_seed(system, prompt, str(max_tokens))}"
	if not refresh:
		cached = frappe.cache.get_value(cache_key)
		if cached is not None:
			return cached
	answer = _request_planner(prompt, system=system, max_tokens=max_tokens)
	frappe.cache.set_value(cache_key, answer, expires_in_sec=CACHE_SECONDS)
	return answer


def _request_planner(prompt, *, system, max_tokens):
	base_url, model, timeout = _qwen_config()
	payload = {
		"model": model,
		"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
		"response_format": {"type": "json_object"},
		"temperature": 0,
		# The same request gives the same plan: the seed follows the prompt, not the clock.
		"seed": request_seed(system, prompt),
		"max_tokens": max_tokens,
	}
	try:
		response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=(10, timeout))
	except requests.RequestException as exc:
		frappe.throw(_("The planner is unavailable at {0}: {1}").format(base_url, str(exc)))
	if not response.ok:
		frappe.throw(_("The planner request failed ({0}): {1}").format(response.status_code, response.text[:300]))
	try:
		return json.loads(response.json()["choices"][0]["message"]["content"])
	except (KeyError, IndexError, TypeError, ValueError) as exc:
		frappe.throw(_("The planner returned invalid JSON: {0}").format(str(exc)))
