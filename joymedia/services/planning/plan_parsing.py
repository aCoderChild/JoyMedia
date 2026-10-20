"""Ask the language model for a video plan and turn its answer into checked shots.

The token budget, the HTTP call, normalising each shot's fields and motion plan, and rejecting a plan that does not fit
the brief.
"""

import itertools
import json
import math
import time

import frappe
import requests
from frappe import _

from joymedia.services.runtime.endpoints import planner_context_window

DEFAULT_MAX_MODEL_LEN = 4096
MIN_PLAN_COMPLETION_TOKENS = 700


def _request_plan(base_url, payload, timeout):
	"""Send one planner request; return the parsed plan, or None when the answer was cut off."""
	response = None
	for attempt in range(3):
		try:
			response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=(10, timeout))
			break
		except requests.ConnectionError:
			if attempt < 2:
				time.sleep(1)
		except requests.Timeout:
			frappe.throw(
				_("The AI planner did not return a video plan within {0} seconds.").format(int(timeout))
			)
	if response is None:
		frappe.throw(
			_(
				"The AI planner is unavailable at {0}. Check its service or SSH tunnel, then try again."
			).format(base_url)
		)
	if not response.ok:
		frappe.throw(
			_("The AI planner request failed ({0}): {1}").format(response.status_code, response.text)
		)
	try:
		body = response.json()
		choice = body["choices"][0]
		content = choice["message"]["content"]
	except (KeyError, IndexError, TypeError, ValueError) as exc:
		frappe.throw(_("The AI planner returned an invalid response: {0}").format(str(exc)))
	try:
		return json.loads(content)
	except (TypeError, ValueError):
		# Keep operational evidence without logging the brief or reference data.
		frappe.logger("joymedia.planner").warning(
			"Planner returned invalid JSON (finish_reason=%s, output_chars=%s, max_tokens=%s).",
			choice.get("finish_reason"),
			len(str(content or "")),
			payload.get("max_tokens"),
		)
		# Usually the plan ran past max_tokens; the caller retries with compact output limits.
		return None


def _plan_shots(result):
	return result.get("shots") if isinstance(result, dict) and isinstance(result.get("shots"), list) else []


def _completion_budget(base_url, payload):
	"""Fit max_tokens into the planner's context window instead of failing with HTTP 400."""
	requested = int(payload.get("max_tokens") or 0)
	max_model_len = planner_context_window(DEFAULT_MAX_MODEL_LEN)
	prompt_tokens = None
	try:
		response = requests.post(
			f"{base_url.rsplit('/v1', 1)[0]}/tokenize",
			json={"model": payload["model"], "messages": payload["messages"]},
			timeout=(5, 20),
		)
		if response.ok:
			data = response.json()
			prompt_tokens = int(data["count"])
			max_model_len = int(data.get("max_model_len") or max_model_len)
	except (requests.RequestException, KeyError, TypeError, ValueError):
		prompt_tokens = None
	if prompt_tokens is None:
		# Conservative estimate when the server has no /tokenize endpoint.
		prompt_tokens = sum(len(str(message.get("content") or "")) for message in payload["messages"]) // 3
	available = max_model_len - prompt_tokens - 64
	if available < MIN_PLAN_COMPLETION_TOKENS:
		frappe.throw(
			_(
				"The video brief and references are too long for the AI planner. "
				"Shorten the video idea or global instructions, or remove some references."
			)
		)
	return min(requested, available)


def _normalize_planner_plan(
	result,
	reference_image_count=0,
	generation_mode="Multi-shot",
	reference_images=None,
	workflow_input_contract=None,
	total_video_duration=None,
):
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
			shot.get("video_generation_prompt"),
			shot.get("prompt"),
			shot.get("video_prompt"),
			shot.get("description"),
		)
		normalized = {
			"shot_number": shot.get("shot_number") or index,
			"shot_name": _first_non_empty(shot.get("shot_name"), f"Shot {index}"),
			"generation_prompt": generation_prompt,
			"image_prompt": _first_non_empty(
				shot.get("image_prompt"), shot.get("image_generation_prompt"), generation_prompt
			),
			"start_state": str(shot.get("start_state") or "").strip(),
			"end_state": str(shot.get("end_state") or "").strip(),
			"handoff_type": str(shot.get("handoff_type") or "").strip(),
			"continuity_mode": "Continue"
			if str(shot.get("continuity_mode") or "").strip().casefold() == "continue"
			else "New Scene",
			"motion_plan": _normalized_motion_plan(
				shot.get("motion_plan") or shot.get("temporal_plan"),
				shot.get("duration_seconds"),
				generation_prompt,
			),
			"caption": str(shot.get("caption") or "").strip()[:120],
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
	if (
		generation_mode == "Multi-shot"
		and reference_images
		and len(normalized_shots) == len(reference_images)
		and all(item.get("reference_key") for item in reference_images)
	):
		single_image_role = next(
			(
				item["role"]
				for item in workflow_input_contract or []
				if item.get("min_count") == 1
				and item.get("max_count") == 1
				and item.get("accepted_media_type") in ("Image", "Any")
			),
			None,
		)
		if single_image_role:
			for shot, image in zip(normalized_shots, reference_images, strict=False):
				shot["references"] = [
					{
						"reference_key": image["reference_key"],
						"usage_role": single_image_role,
					}
				]
	# A workflow can expose several required image slots under one semantic role,
	# either as a File Paths list or as separate scalar bindings. The planner may
	# return fewer references than the selected project pool provides. Fill the
	# missing slots here so validation and later Shot creation use the same
	# deterministic assignment.
	if reference_images and workflow_input_contract:
		required_reference_contracts = [
			contract
			for contract in workflow_input_contract
			if contract.get("min_count", 0) > 0 and contract.get("accepted_media_type") in ("Image", "Any")
		]
		for shot in normalized_shots:
			for contract in required_reference_contracts:
				role = contract["role"]
				if generation_mode == "Continuous" and shot["shot_number"] > 1 and role == "first_frame":
					continue
				references = shot.setdefault("references", [])
				role_references = [
					reference
					for reference in references
					if frappe.scrub(reference.get("usage_role") or "") == role
				]
				needed = int(contract["min_count"]) - len(role_references)
				if needed <= 0:
					continue
				existing_keys = {reference.get("reference_key") for reference in role_references}
				# Keep the assignment stable per shot while allowing a planner-supplied
				# first reference to remain the first slot.
				start = max(0, int(shot.get("shot_number") or 1) - 1)
				pool = []
				for offset in range(len(reference_images)):
					candidate = reference_images[(start + offset) % len(reference_images)]
					key = candidate.get("reference_key")
					if key and key not in existing_keys:
						pool.append(candidate)
						existing_keys.add(key)
						if len(pool) == needed:
							break
				for image in pool[:needed]:
					references.append({"reference_key": image["reference_key"], "usage_role": role})
	if (
		total_video_duration is not None
		and generation_mode == "Multi-shot"
		and reference_images
		and len(normalized_shots) == len(reference_images)
	):
		equal_duration = float(total_video_duration) / len(normalized_shots)
		for shot in normalized_shots:
			shot["duration_seconds"] = equal_duration
	return {"shots": normalized_shots}


def _first_non_empty(*values):
	for value in values:
		text = str(value or "").strip()
		if text:
			return text
	return ""


def _normalized_motion_plan(value, duration, fallback_action):
	"""Keep valid director timing or create one honest legacy interval.

	The fallback represents the existing prompt as a single action rather than
	inventing a schedule. New planner responses are expected to provide richer actions.
	"""
	actions = value.get("actions") if isinstance(value, dict) else value
	if not isinstance(actions, list):
		actions = []
	try:
		limit = float(duration)
	except (TypeError, ValueError):
		limit = 0
	normalized = []
	for action in actions:
		if not isinstance(action, dict):
			continue
		try:
			start, end = float(action["start"]), float(action["end"])
		except (KeyError, TypeError, ValueError):
			continue
		text = str(action.get("action") or "").strip()
		if text:
			normalized.append({"start": start, "end": end, "action": text})
	from joymedia.services.scene.contract import read_contract

	result = {
		"actions": normalized
		or ([{"start": 0, "end": limit, "action": fallback_action}] if limit > 0 else [])
	}
	if isinstance(value, dict) and "camera_intent" in value:
		from joymedia.services.planning.camera import camera_intent

		result["camera_intent"] = camera_intent(value["camera_intent"])
	if isinstance(value, dict) and "camera_motion" in value:
		if value["camera_motion"] not in ("locked", "moving"):
			raise ValueError("Camera motion must be locked or moving.")
		result["camera_motion"] = value["camera_motion"]
	from joymedia.services.scene.artwork import placements

	artwork = placements(value)
	if artwork:
		result["artwork_placements"] = artwork
	contract = read_contract(value, limit)
	if isinstance(value, dict) and "shot_structure" in value:
		from joymedia.services.planning.shot_structure import shot_structure

		result["shot_structure"] = shot_structure(value["shot_structure"], contract)
	if isinstance(value, dict) and "required_references" in value:
		from joymedia.services.planning.shot_structure import reference_requirements

		result["required_references"] = reference_requirements(value["required_references"])
	if contract is not None:
		result["scene_contract"] = contract
		# Refuse an unreviewable plan at authoring time, before any GPU admission.
		from joymedia.services.scene.evidence import claims_for

		claims_for(result, limit, fallback_action)
	return result


def _rescale_motion_plan(shot, previous_duration):
	"""Keep persisted seconds intervals aligned when plan durations are normalized."""
	new_duration = float(shot["duration_seconds"])
	if not previous_duration or previous_duration <= 0 or new_duration == previous_duration:
		return
	factor = new_duration / previous_duration
	for action in (shot.get("motion_plan") or {}).get("actions") or []:
		action["start"] *= factor
		action["end"] *= factor
	for event in ((shot.get("motion_plan") or {}).get("scene_contract") or {}).get("events") or []:
		event["start"] *= factor
		event["end"] *= factor


def _validate_video_plan(
	result,
	reference_image_count=0,
	shot_count=None,
	generation_mode="Multi-shot",
	workflow_input_contract=None,
	total_video_duration=None,
):
	if not isinstance(result, dict) or not isinstance(result.get("shots"), list):
		frappe.throw(_("The AI planner response must contain a shots list."))
	if not result["shots"]:
		frappe.throw(_("The AI planner response must contain at least one shot."))
	if len(result["shots"]) > 8:
		frappe.throw(_("The AI planner response must not contain more than 8 creative shots."))
	if shot_count is not None and len(result["shots"]) != shot_count:
		frappe.throw(
			_("The AI planner returned {0} shots; expected {1}.").format(len(result["shots"]), shot_count)
		)

	required_fields = {"shot_number", "generation_prompt"}

	normalized_shots = []
	for shot in result["shots"]:
		if not isinstance(shot, dict) or not required_fields.issubset(shot):
			frappe.throw(_("Each planner shot must contain the required video plan fields."))
		if type(shot["shot_number"]) is not int or shot["shot_number"] < 1:
			frappe.throw(_("Shot number must be a positive integer."))
		prompt = str(shot.get("generation_prompt") or "").strip()
		if not prompt:
			frappe.throw(
				_("The AI planner returned an empty generation_prompt for shot {0}.").format(
					shot.get("shot_number", "?")
				)
			)
		try:
			duration_seconds = float(shot["duration_seconds"])
		except (KeyError, TypeError, ValueError):
			frappe.throw(_("Every planner shot must contain a numeric duration_seconds."))
		if not math.isfinite(duration_seconds) or duration_seconds <= 0:
			frappe.throw(_("Shot duration must be greater than zero."))
		normalized = {
			"shot_number": shot["shot_number"],
			"shot_name": str(shot.get("shot_name") or f"Shot {shot['shot_number']}").strip(),
			"generation_prompt": prompt,
			"image_prompt": str(
				shot.get("image_prompt") or shot.get("image_generation_prompt") or prompt
			).strip(),
			"start_state": str(shot.get("start_state") or "").strip(),
			"end_state": str(shot.get("end_state") or "").strip(),
			"handoff_type": str(shot.get("handoff_type") or "").strip(),
			"continuity_mode": "Continue"
			if str(shot.get("continuity_mode") or "").strip().casefold() == "continue"
			else "New Scene",
			"motion_plan": _normalized_motion_plan(
				shot.get("motion_plan") or shot.get("temporal_plan"), duration_seconds, prompt
			),
			"duration_seconds": duration_seconds,
			"references": shot.get("references") if isinstance(shot.get("references"), list) else [],
		}
		actions = normalized["motion_plan"]["actions"]
		previous_end = 0.0
		for action in actions:
			if (
				action["start"] < previous_end
				or action["start"] < 0
				or action["end"] <= action["start"]
				or action["end"] > duration_seconds + 0.001
			):
				frappe.throw(
					_("Shot {0} has an invalid seconds-based temporal plan.").format(shot["shot_number"])
				)
			previous_end = action["end"]
		if normalized["handoff_type"] and normalized["handoff_type"] not in {
			"motion_continuation",
			"pose_transition",
			"camera_transition",
			"ending",
		}:
			frappe.throw(_("Shot {0} has an unsupported handoff type.").format(shot["shot_number"]))
		contract_by_role = {
			item["role"]: item for item in (workflow_input_contract or []) if item.get("role")
		}
		role_counts = {}
		for reference in normalized["references"]:
			if not isinstance(reference, dict) or not str(reference.get("reference_key") or "").strip():
				frappe.throw(_("Each planner shot reference must contain a reference_key."))
			usage_role = frappe.scrub(reference.get("usage_role") or "")
			if not usage_role:
				frappe.throw(_("Each planner shot reference must contain a usage_role."))
			contract = contract_by_role.get(usage_role)
			if workflow_input_contract is not None and not contract:
				frappe.throw(
					_("The AI planner returned unsupported workflow input role '{0}'.").format(usage_role)
				)
			role_counts[usage_role] = role_counts.get(usage_role, 0) + 1
			if (
				contract
				and role_counts[usage_role] > 1
				and not contract.get("allow_multiple")
				and int(contract.get("max_count") or 1) <= 1
			):
				frappe.throw(
					_("Workflow input role '{0}' does not allow multiple references.").format(usage_role)
				)
			if contract and contract.get("max_count") and role_counts[usage_role] > contract["max_count"]:
				frappe.throw(
					_("Workflow input role '{0}' accepts at most {1} references.").format(
						usage_role, contract["max_count"]
					)
				)
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
		for contract in workflow_input_contract or []:
			# Continuous shots after the first start from the previous generated
			# Last Frame artifact; they must not repeat a static first-frame image.
			if (
				generation_mode == "Continuous"
				and normalized["shot_number"] > 1
				and contract["role"] == "first_frame"
			):
				continue
			count = role_counts.get(contract["role"], 0)
			if count < contract.get("min_count", 0):
				frappe.throw(
					_(
						"Shot {0} needs {1} reference image(s) for the selected workflow. "
						"Add the required references or select a workflow with a compatible input contract."
					).format(normalized["shot_number"], contract["min_count"])
				)
		normalized_shots.append(normalized)
	if total_video_duration is not None:
		target_duration = float(total_video_duration)
		if (
			generation_mode == "Multi-shot"
			and reference_image_count
			and len(normalized_shots) == reference_image_count
		):
			equal_duration = target_duration / len(normalized_shots)
			for shot in normalized_shots:
				previous_duration = shot["duration_seconds"]
				shot["duration_seconds"] = equal_duration
				_rescale_motion_plan(shot, previous_duration)
			return {"shots": normalized_shots}
		plan_duration = sum(shot["duration_seconds"] for shot in normalized_shots)
		if not math.isfinite(target_duration) or target_duration <= 0 or plan_duration <= 0:
			frappe.throw(_("Video plan duration must be a positive finite number."))
		scale = target_duration / plan_duration
		for shot in normalized_shots[:-1]:
			previous_duration = shot["duration_seconds"]
			shot["duration_seconds"] *= scale
			_rescale_motion_plan(shot, previous_duration)
		if normalized_shots:
			shot_duration = target_duration - sum(shot["duration_seconds"] for shot in normalized_shots[:-1])
			if shot_duration <= 0 or not math.isfinite(shot_duration):
				frappe.throw(_("Video plan durations must sum to the requested duration."))
			previous_duration = normalized_shots[-1]["duration_seconds"]
			normalized_shots[-1]["duration_seconds"] = shot_duration
			_rescale_motion_plan(normalized_shots[-1], previous_duration)

	if (
		generation_mode == "Multi-shot"
		and reference_image_count
		and all(
			"first_frame_reference_image_index" in shot and "last_frame_reference_image_index" in shot
			for shot in normalized_shots
		)
	):
		for current, following in itertools.pairwise(normalized_shots):
			if current["last_frame_reference_image_index"] != following["first_frame_reference_image_index"]:
				frappe.throw(
					_("Multi-shot boundary is invalid between shots {0} and {1}.").format(
						current["shot_number"], following["shot_number"]
					)
				)
	result["shots"] = normalized_shots
