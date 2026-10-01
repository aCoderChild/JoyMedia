import json
import time

import frappe
import requests
from frappe import _


DEFAULT_TIMEOUT = 600


def _qwen_config():
	base_url = frappe.conf.get("qwen_base_url")
	model = frappe.conf.get("qwen_model")
	if not base_url:
		frappe.throw(_("qwen_base_url is not configured."))
	if not model:
		frappe.throw(_("qwen_model is not configured."))
	try:
		timeout = float(frappe.conf.get("qwen_timeout", DEFAULT_TIMEOUT))
	except (TypeError, ValueError):
		frappe.throw(_("qwen_timeout must be a positive number of seconds."))
	if timeout <= 0:
		frappe.throw(_("qwen_timeout must be a positive number of seconds."))
	return base_url.rstrip("/"), model, timeout


def generate_shot_revision(*, instruction, shot, product_name=""):
	"""Ask Qwen to replace one canonical shot prompt."""
	base_url, model, timeout = _qwen_config()
	current_prompt = str(shot.get("generation_prompt") or "").strip()
	user_prompt = (
		"Revise exactly one cinematic commercial shot. Return only valid JSON.\n\n"
		f"PRODUCT: {product_name}\n"
		f"USER INSTRUCTION: {instruction}\n\n"
		"CURRENT SHOT PROMPT:\n"
		f"{current_prompt}\n\n"
		"Return this shape:\n"
		'{"summary":"short explanation",'
		'"changes":[{"field":"Shot Prompt","detail":"..."}],'
		'"generation_prompt":"..."}\n'
		"Return one complete replacement generation_prompt, preserving details not changed by the instruction."
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
		frappe.throw(_("Qwen did not return a shot revision within {0} seconds.").format(int(timeout)))
	except requests.RequestException as exc:
		frappe.throw(_("Qwen is unavailable at {0}: {1}").format(base_url, str(exc)))
	if not response.ok:
		frappe.throw(_("Qwen request failed ({0}): {1}").format(response.status_code, response.text))
	try:
		result = json.loads(response.json()["choices"][0]["message"]["content"])
	except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
		frappe.throw(_("Qwen returned invalid shot revision JSON: {0}").format(str(exc)))
	if not isinstance(result, dict):
		frappe.throw(_("Qwen returned an invalid shot revision."))
	generation_prompt = str(result.get("generation_prompt") or "").strip()
	if not generation_prompt:
		frappe.throw(_("Qwen returned an empty generation_prompt for the shot revision."))
	result["generation_prompt"] = generation_prompt
	result["changes"] = result.get("changes") if isinstance(result.get("changes"), list) else []
	result["summary"] = str(result.get("summary") or "Shot changes are ready to review.").strip()
	return result


def generate_video_plan(
	*,
	product_name: str,
	video_idea: str,
	total_video_duration: float,
	target_fps: float,
	shot_count: int | None = None,
	reference_images: list[dict] | None = None,
	reference_media: list[dict] | None = None,
	video_style: str | None = None,
	generation_mode: str = "Multi-shot",
	global_instructions: str | None = None,
	format_preset: str | None = None,
) -> dict:
	"""Create one structured storyboard from the project prompt and selected references.

	Reference media is planning context only. Actual workflow inputs are resolved by
	JoyMedia after planning so Asset/Asset Version stays separate from Generation Input.
	"""
	generation_mode = {"Independent": "Multi-shot", "Chained": "Continuous", "Consistency": "Continuous"}.get(
		generation_mode, generation_mode
	)
	if generation_mode not in ("Multi-shot", "Continuous"):
		frappe.throw(_("Select Continuous or Multi-shot generation mode."))
	base_url, model, timeout = _qwen_config()

	instruction = """
You are the creative planner for JoyMedia product videos.
Understand the complete video idea first, then divide it into a coherent sequence
of creative shots. For every shot, return exactly one detailed generation_prompt.
Put subject, action, camera, environment, lighting, continuity and relevant sound
intent inside that one prompt rather than separate creative fields.

Project reference media are named ingredients/context. Use their reference_key when
a shot intentionally uses one. Never emit Asset Version IDs or image indexes.
""".strip()

	if video_style:
		instruction += f"\n\nVIDEO STYLE / WORKFLOW KEY:\n{video_style}"
	if format_preset:
		instruction += f"\n\nOUTPUT FORMAT:\n{format_preset}. Frame each shot appropriately for this format."
	if global_instructions:
		instruction += f"\n\nGLOBAL INSTRUCTIONS FOR EVERY SHOT:\n{global_instructions}"
	if generation_mode == "Continuous":
		instruction += (
			"\n\nGENERATION MODE: CONTINUOUS\n"
			"The first shot starts from a selected image. Later shots continue from the previous generated last frame. "
			"Plan motion that can continue naturally while preserving product identity and scene state."
		)
	else:
		instruction += (
			"\n\nGENERATION MODE: MULTI-SHOT\n"
			"Shots are generated from explicitly resolved keyframes/references. Keep boundaries coherent."
		)

	response_shape = (
		'{"shots":[{"shot_number":1,"shot_name":"...",'
		'"duration_seconds":5,"generation_prompt":"...",'
		'"references":[{"reference_key":"hero_product","usage_role":"product_reference"}]}]}'
	)
	user_prompt = (
		f"{instruction}\n\n"
		f"PRODUCT NAME\n{product_name}\n\n"
		f"VIDEO IDEA\n{video_idea or ''}\n\n"
		f"TOTAL VIDEO DURATION: {total_video_duration} seconds\n"
		f"TARGET FPS: {target_fps}\n"
		f"SHOT COUNT GUIDANCE: {shot_count if shot_count is not None else 'Choose the appropriate number of creative shots; do not use model frame capacity to choose it.'}\n\n"
		+ (f"Return exactly {shot_count} shots. " if shot_count is not None else "Choose a coherent storyboard structure, normally between 1 and 8 shots. ")
		+ "Organize the shots into a coherent narrative progression.\n\n"
		"IMPORTANT OUTPUT RULES:\n"
		"- Every shot MUST contain a positive integer shot_number.\n"
		"- Every shot MUST contain one non-empty generation_prompt.\n"
		"- Every shot MUST contain a positive duration_seconds value.\n"
		"- Never return null or empty generation_prompt values.\n"
		"- References must use only supplied reference_key values and semantic usage_role values.\n\n"
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
			+ f"JoyMedia will resolve {len(reference_images)} selected image references after planning. "
			"Do not output image indexes."
		)
		for image in reference_images:
			user_prompt += f"\nIMAGE {image['index']}: {image['asset_name']}"

	request_payload = {
		"model": model,
		"messages": [
			{"role": "system", "content": "You produce structured JSON video plans. Do not include markdown fences or commentary."},
			{"role": "user", "content": user_prompt},
		],
		"response_format": {"type": "json_object"},
		"temperature": 0.2,
		"max_tokens": 3000,
	}

	response = None
	for attempt in range(3):
		try:
			response = requests.post(f"{base_url}/chat/completions", json=request_payload, timeout=(10, timeout))
			break
		except requests.ConnectionError:
			if attempt < 2:
				time.sleep(1)
		except requests.Timeout:
			frappe.throw(_("Qwen did not return a video plan within {0} seconds.").format(int(timeout)))
	if response is None:
		frappe.throw(_("Qwen is unavailable at {0}. Check the Qwen service or SSH tunnel, then try again.").format(base_url))
	if not response.ok:
		frappe.throw(_("Qwen request failed ({0}): {1}").format(response.status_code, response.text))
	try:
		result = json.loads(response.json()["choices"][0]["message"]["content"])
	except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
		frappe.throw(_("Qwen returned invalid video plan JSON: {0}").format(str(exc)))

	result = _normalize_qwen_plan(
		result,
		reference_image_count=len(reference_images or []),
		generation_mode=generation_mode,
	)
	_validate_video_plan(
		result,
		reference_image_count=len(reference_images or []),
		shot_count=shot_count,
		generation_mode=generation_mode,
	)
	return result


def _normalize_qwen_plan(result, reference_image_count=0, generation_mode="Multi-shot"):
	"""Normalize model output without inventing semantic reference assignments."""
	if not isinstance(result, dict) or not isinstance(result.get("shots"), list):
		return result

	normalized_shots = []
	for index, shot in enumerate(result["shots"], start=1):
		if not isinstance(shot, dict):
			normalized_shots.append(shot)
			continue
		generation_prompt = _first_non_empty(
			shot.get("generation_prompt"),
			shot.get("prompt"),
			shot.get("video_prompt"),
			shot.get("description"),
		)
		normalized = {
			"shot_number": shot.get("shot_number") or index,
			"shot_name": _first_non_empty(shot.get("shot_name"), f"Shot {index}"),
			"generation_prompt": generation_prompt,
			"duration_seconds": shot.get("duration_seconds"),
			"references": shot.get("references") if isinstance(shot.get("references"), list) else [],
		}
		for fieldname in (
			"reference_image_index",
			"first_frame_reference_image_index",
			"last_frame_reference_image_index",
		):
			if fieldname in shot:
				normalized[fieldname] = shot[fieldname]
		normalized_shots.append(normalized)
	return {"shots": normalized_shots}


def _first_non_empty(*values):
	for value in values:
		text = str(value or "").strip()
		if text:
			return text
	return ""


def _validate_video_plan(result, reference_image_count=0, shot_count=None, generation_mode="Multi-shot"):
	if not isinstance(result, dict) or not isinstance(result.get("shots"), list):
		frappe.throw(_("Qwen video plan must contain a shots list."))
	if not result["shots"]:
		frappe.throw(_("Qwen video plan must contain at least one shot."))
	if len(result["shots"]) > 8:
		frappe.throw(_("Qwen video plan must not contain more than 8 creative shots."))
	if shot_count is not None and len(result["shots"]) != shot_count:
		frappe.throw(_("Qwen returned {0} shots; expected {1}.").format(len(result["shots"]), shot_count))

	required_fields = {"shot_number", "generation_prompt"}

	normalized_shots = []
	for shot in result["shots"]:
		if not isinstance(shot, dict) or not required_fields.issubset(shot):
			frappe.throw(_("Each Qwen shot must contain the required video plan fields."))
		if type(shot["shot_number"]) is not int or shot["shot_number"] < 1:
			frappe.throw(_("Shot number must be a positive integer."))
		prompt = str(shot.get("generation_prompt") or "").strip()
		if not prompt:
			frappe.throw(_("Qwen returned an empty generation_prompt for shot {0}.").format(shot.get("shot_number", "?")))
		try:
			duration_seconds = float(shot["duration_seconds"])
		except (KeyError, TypeError, ValueError):
			frappe.throw(_("Every Qwen shot must contain a numeric duration_seconds."))
		if duration_seconds <= 0:
			frappe.throw(_("Shot duration must be greater than zero."))
		normalized = {
			"shot_number": shot["shot_number"],
			"shot_name": str(shot.get("shot_name") or f"Shot {shot['shot_number']}").strip(),
			"generation_prompt": prompt,
			"duration_seconds": duration_seconds,
			"references": shot.get("references") if isinstance(shot.get("references"), list) else [],
		}
		for reference in normalized["references"]:
			if not isinstance(reference, dict) or not str(reference.get("reference_key") or "").strip():
				frappe.throw(_("Each Qwen shot reference must contain a reference_key."))
			usage_role = frappe.scrub(reference.get("usage_role") or "")
			if not usage_role:
				frappe.throw(_("Each Qwen shot reference must contain a usage_role."))
			reference["reference_key"] = str(reference["reference_key"]).strip()
			reference["usage_role"] = usage_role
		if reference_image_count:
			for fieldname in (
				"reference_image_index",
				"first_frame_reference_image_index",
				"last_frame_reference_image_index",
			):
				if fieldname not in shot:
					continue
				image_index = shot[fieldname]
				if type(image_index) is not int or image_index < 1 or image_index > reference_image_count:
					frappe.throw(_("Invalid reference image index."))
				normalized[fieldname] = image_index
		normalized_shots.append(normalized)

	if generation_mode == "Multi-shot" and reference_image_count and all(
		"first_frame_reference_image_index" in shot and "last_frame_reference_image_index" in shot
		for shot in normalized_shots
	):
		for current, following in zip(normalized_shots, normalized_shots[1:]):
			if current["last_frame_reference_image_index"] != following["first_frame_reference_image_index"]:
				frappe.throw(
					_("Multi-shot boundary is invalid between shots {0} and {1}.").format(
						current["shot_number"], following["shot_number"]
					)
				)
	result["shots"] = normalized_shots
