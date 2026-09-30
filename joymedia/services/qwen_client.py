import json
import time

import frappe
import requests
from frappe import _


DEFAULT_TIMEOUT = 600


def generate_shot_revision(*, instruction, shot, product_name="", campaign_brief=""):
	"""Ask the configured text model for structured changes to one shot."""
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

	current = {
		"subject_identity": shot.get("subject_identity") or "",
		"action_plot": shot.get("action_plot") or "",
		"camera_direction": shot.get("camera_direction") or "",
		"environment": shot.get("environment") or "",
		"audio_direction": shot.get("audio_direction") or "",
	}
	user_prompt = (
		"Revise exactly one cinematic commercial shot. Return only valid JSON.\n\n"
		f"PRODUCT: {product_name}\n"
		f"CAMPAIGN BRIEF: {campaign_brief}\n"
		f"USER INSTRUCTION: {instruction}\n\n"
		"CURRENT SHOT:\n"
		f"{json.dumps(current, ensure_ascii=False)}\n\n"
		"Return this shape:\n"
		'{"summary":"short explanation",'
		'"changes":[{"field":"Camera","detail":"..."}],'
		'"shot":{"subject_identity":"...","action_plot":"...",'
		'"camera_direction":"...","environment":"...","audio_direction":"..."}}\n'
		"Preserve current values for fields the instruction does not change."
	)
	payload = {
		"model": model,
		"messages": [
			{
				"role": "system",
				"content": "You revise structured shot specifications. Do not include markdown fences or commentary.",
			},
			{"role": "user", "content": user_prompt},
		],
		"response_format": {"type": "json_object"},
		"temperature": 0.2,
		"max_tokens": 1200,
	}
	try:
		response = requests.post(
			f"{base_url.rstrip('/')}/chat/completions",
			json=payload,
			timeout=(10, timeout),
		)
	except requests.Timeout:
		frappe.throw(_("Qwen did not return a shot revision within {0} seconds.").format(int(timeout)))
	except requests.RequestException as exc:
		frappe.throw(_("Qwen is unavailable at {0}: {1}").format(base_url, str(exc)))
	if not response.ok:
		frappe.throw(_("Qwen request failed ({0}): {1}").format(response.status_code, response.text))
	try:
		content = response.json()["choices"][0]["message"]["content"]
		result = json.loads(content)
	except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
		frappe.throw(_("Qwen returned invalid shot revision JSON: {0}").format(str(exc)))

	if not isinstance(result, dict) or not isinstance(result.get("shot"), dict):
		frappe.throw(_("Qwen returned an invalid shot revision."))
	result["shot"] = {
		field: str(result["shot"].get(field) or current[field]).strip()
		for field in current
	}
	result["changes"] = result.get("changes") if isinstance(result.get("changes"), list) else []
	result["summary"] = str(result.get("summary") or "Shot changes are ready to review.").strip()
	return result


def generate_video_plan(
	*,
	product_name: str,
	video_idea: str,
	total_video_duration: float,
	target_fps: float,
	shot_count: int,
	reference_template: dict | None = None,
	reference_images: list[dict] | None = None,
	video_style: str | None = None,
	generation_mode: str = "Multi-shot",
) -> dict:
	generation_mode = {"Independent": "Multi-shot", "Chained": "Continuous", "Consistency": "Continuous"}.get(
		generation_mode, generation_mode
	)
	if generation_mode not in ("Multi-shot", "Continuous"):
		frappe.throw(_("Select Continuous or Multi-shot generation mode."))

	base_url = frappe.conf.get("qwen_base_url")
	model = frappe.conf.get("qwen_model")
	if not base_url:
		frappe.throw(_("qwen_base_url is not configured."))
	if not model:
		frappe.throw(_("qwen_model is not configured."))

	timeout = frappe.conf.get("qwen_timeout", DEFAULT_TIMEOUT)
	try:
		timeout = float(timeout)
	except (TypeError, ValueError):
		frappe.throw(_("qwen_timeout must be a positive number of seconds."))
	if timeout <= 0:
		frappe.throw(_("qwen_timeout must be a positive number of seconds."))

	base_instruction = """
You are the creative planner for JoyMedia product videos.

Understand the complete video idea first, then divide it into a coherent
sequence of creative shots. For every shot, produce exactly one detailed
generation_prompt suitable for the configured video model. The prompt should
contain the visual action, subject, camera, environment, lighting, continuity,
and audio intent when relevant. JoyMedia assigns reference assets separately;
do not claim to inspect their contents or emit reference image indexes.
""".strip()

	if reference_template:
		instruction = (
			base_instruction
			+ """

REFERENCE TEMPLATE:
Preserve the reference template's cinematography,
pacing, composition, scene progression, motion style
and lighting language.

Adapt the content to the supplied product and campaign brief,
video idea and project reference images.
"""
		).strip()
	else:
		instruction = base_instruction
	if video_style:
		instruction += (
			"\n\nVIDEO STYLE:\n"
			f"{video_style}\n"
			"Use this style to guide the shot pacing, framing, movement, lighting, "
			"environment, and sound while keeping the product and story consistent."
		)
	if generation_mode in ("Continuous", "Consistency"):
		instruction += (
			"\n\nGENERATION MODE: CONSISTENCY\n"
			"JoyMedia will attach the first shot to the supplied reference image. Each later shot "
			"must continue from the previous shot's generated last frame. Describe the next "
			"movement from the existing pose and preserve product geometry, color, orientation, "
			"and scene state."
		)
	else:
		instruction += (
			"\n\nGENERATION MODE: MULTI-SHOT\n"
			"JoyMedia will attach first-frame and last-frame references after planning. "
			"Keep the shots coherent as a connected keyframe sequence."
		)

	response_shape = (
		'{"shots":[{"shot_number":1,"shot_name":"...",'
		'"duration_seconds":5,"generation_prompt":"..."}]}'
	)

	user_prompt = (
		f"{instruction}\n\n"
		f"PRODUCT NAME\n{product_name}\n\n"
		f"VIDEO IDEA\n{video_idea or ''}\n\n"
		f"TOTAL VIDEO DURATION: {total_video_duration} seconds\n"
		f"TARGET FPS: {target_fps}\n"
		f"NUMBER OF SHOTS: {shot_count}\n\n"
		f"Return exactly {shot_count} shots. Organize the shots into a coherent narrative progression.\n\n"
		"IMPORTANT OUTPUT RULES:\n"
		"- Every shot MUST contain a positive integer shot_number.\n"
		"- Every shot MUST contain one non-empty generation_prompt.\n"
		"- shot_name and duration_seconds are optional planning metadata.\n"
		"- Never return null or empty generation_prompt values.\n\n"
		"Return only valid JSON with this shape:\n"
		f"{response_shape}"
	)
	if reference_template:
		user_prompt += "\n\nREFERENCE TEMPLATE\n" + json.dumps(reference_template, ensure_ascii=False)
	if reference_images:
		user_prompt += (
			"\n\nAVAILABLE REFERENCE ASSETS\n"
			+ f"JoyMedia will assign from these {len(reference_images)} assets after planning.\n"
			"Do not output reference image indexes or claim to see the asset contents."
		)
		for image in reference_images:
			user_prompt += (
				f"\nREFERENCE IMAGE {image['index']}: "
				f"{image['asset_name']}"
			)
	user_content = user_prompt

	request_payload = {
		"model": model,
		"messages": [
			{
				"role": "system",
				"content": "You produce structured JSON video plans. Do not include markdown fences or commentary.",
			},
			{"role": "user", "content": user_content},
		],
		"response_format": {"type": "json_object"},
		"temperature": 0.2,
		"max_tokens": 3000,
	}
	response = None
	for attempt in range(3):
		try:
			response = requests.post(
				f"{base_url.rstrip('/')}/chat/completions",
				json=request_payload,
				timeout=(10, timeout),
			)
			break
		except requests.ConnectionError as exc:
			if attempt < 2:
				time.sleep(1)
		except requests.Timeout:
			frappe.throw(
				_("Qwen did not return a video plan within {0} seconds.").format(int(timeout))
			)

	if response is None:
		frappe.throw(
			_("Qwen is unavailable at {0}. Check the Qwen service or SSH tunnel, then try again.").format(
				base_url
			)
		)
	if not response.ok:
		frappe.throw(
			_("Qwen request failed ({0}): {1}").format(response.status_code, response.text)
		)

	try:
		content = response.json()["choices"][0]["message"]["content"]
		result = json.loads(content)
	except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
		frappe.throw(_("Qwen returned invalid video plan JSON: {0}").format(str(exc)))

	result = _normalize_qwen_plan(
		result,
		product_name=product_name,
		video_idea=video_idea,
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


def _normalize_qwen_plan(
	result,
	product_name="",
	video_idea="",
	reference_image_count=0,
	generation_mode="Multi-shot",
):
	"""Adapt the fine-tuned text model output to JoyMedia's canonical plan."""
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
		}
		if shot.get("duration_seconds") is not None:
			normalized["duration_seconds"] = shot.get("duration_seconds")

		# The text model cannot inspect the uploaded images. Reference selection
		# is therefore deterministic backend state, not model output.
		if reference_image_count:
			if generation_mode == "Multi-shot":
				normalized["first_frame_reference_image_index"] = ((index - 1) % reference_image_count) + 1
				normalized["last_frame_reference_image_index"] = (index % reference_image_count) + 1
			elif index == 1:
				normalized["reference_image_index"] = 1

		normalized_shots.append(normalized)

	return {"shots": normalized_shots}


def _first_non_empty(*values):
	for value in values:
		text = str(value or "").strip()
		if text:
			return text
	return ""


def _validate_video_plan(
	result, reference_image_count=0, shot_count=None, generation_mode="Multi-shot"
):
	if not isinstance(result, dict) or not isinstance(result.get("shots"), list):
		frappe.throw(_("Qwen video plan must contain a shots list."))

	if not result["shots"]:
		frappe.throw(_("Qwen video plan must contain at least one shot."))

	if shot_count is not None and len(result["shots"]) != shot_count:
		frappe.throw(_("Qwen returned {0} shots; expected {1}.").format(len(result["shots"]), shot_count))

	required_fields = {"shot_number", "generation_prompt"}
	if reference_image_count and generation_mode == "Multi-shot":
		required_fields.update(
			{"first_frame_reference_image_index", "last_frame_reference_image_index"}
		)

	normalized_shots = []

	for shot in result["shots"]:
		if not isinstance(shot, dict) or not required_fields.issubset(shot):
			frappe.throw(_("Each Qwen shot must contain the required video plan fields."))
		if not str(shot.get("generation_prompt") or "").strip():
			frappe.throw(
				_("Qwen returned an empty generation_prompt for shot {0}.").format(
					shot.get("shot_number", "?")
				)
			)

		if type(shot["shot_number"]) is not int or shot["shot_number"] < 1:
			frappe.throw(_("Shot number must be a positive integer."))

		normalized = {
			"shot_number": shot["shot_number"],
			"shot_name": str(shot.get("shot_name") or f"Shot {shot['shot_number']}").strip(),
			"generation_prompt": str(shot["generation_prompt"]).strip(),
		}
		if shot.get("duration_seconds") is not None:
			try:
				duration_seconds = float(shot["duration_seconds"])
			except (TypeError, ValueError):
				frappe.throw(_("Shot duration must be numeric."))
			if duration_seconds <= 0:
				frappe.throw(_("Shot duration must be greater than zero."))
			normalized["duration_seconds"] = duration_seconds

		if reference_image_count:
			if generation_mode == "Multi-shot":
				first_index = shot["first_frame_reference_image_index"]
				last_index = shot["last_frame_reference_image_index"]
				if any(
					type(index) is not int or index < 1 or index > reference_image_count
					for index in (first_index, last_index)
				):
					frappe.throw(_("Invalid first or last frame reference image index."))
				normalized["first_frame_reference_image_index"] = first_index
				normalized["last_frame_reference_image_index"] = last_index
			elif "reference_image_index" in shot:
				index = shot["reference_image_index"]
				if type(index) is not int or index < 1 or index > reference_image_count:
					frappe.throw(_("Invalid reference image index."))
				normalized["reference_image_index"] = index

		normalized_shots.append(normalized)

	if generation_mode == "Multi-shot" and reference_image_count:
		for current, following in zip(normalized_shots, normalized_shots[1:]):
			if current["last_frame_reference_image_index"] != following[
				"first_frame_reference_image_index"
			]:
				frappe.throw(
					_("Multi-shot boundary is invalid between shots {0} and {1}.").format(
						current["shot_number"], following["shot_number"]
					)
				)

	result["shots"] = normalized_shots
