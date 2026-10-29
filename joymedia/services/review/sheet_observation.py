"""Describe visible sheets before comparing them with authored material traits."""

import json
import re

from joymedia.services.scene.prompt_scope import sheet_material_instruction


def _parse_description(description, configured):
	from joymedia.services.review.consistency import _post_visual_request
	from joymedia.services.runtime.endpoints import structured_response
	from joymedia.services.runtime.sampling import sampling

	prompt = (
		"Extract only what this image description says about a loose paper/tissue/napkin sheet. "
		"Do not infer a requested appearance or correct the description. A retail package and the actor "
		"are not the loose sheet. visibility is visible, absent or unclear. printed_marks lists actual "
		"lettering, logos, cartoons, pictures or printed patterns described ON THE SHEET, excluding "
		"natural folds, creases, shadows and the separate actor. Use an empty list for an explicitly "
		"unmarked sheet or absent sheet, null if unclear. quote must be an exact supporting substring "
		"copied from the description. DESCRIPTION: " + json.dumps(description)
	)
	schema = {
		"type": "object",
		"additionalProperties": False,
		"required": ["visibility", "printed_marks", "quote"],
		"properties": {
			"visibility": {"type": "string", "enum": ["visible", "absent", "unclear"]},
			"printed_marks": {"type": ["array", "null"], "items": {"type": "string"}},
			"quote": {"type": "string"},
		},
	}
	response = _post_visual_request(
		f"{configured.base_url}/chat/completions",
		json={
			"model": configured.model,
			"messages": [{"role": "user", "content": prompt}],
			**structured_response(configured, schema, "sheet_description"),
			**sampling("vision_observation"),
		},
		timeout=(10, configured.timeout),
	)
	response.raise_for_status()
	return json.loads(response.json()["choices"][0]["message"]["content"])


def observe_sheet(picture, *, configured=None):
	from joymedia.services.review.consistency import ask
	from joymedia.services.runtime.endpoints import endpoint

	configured = configured or endpoint("vision")
	# A direct "is this unprinted?" check repeatedly copied its requested answer
	# despite a large visible cartoon. Free description saw that same cartoon.
	observed = ask(
		picture,
		"Describe the visible image in detail. Describe the surface of the loose sheet, including any "
		"colored shapes, drawings or lettering, or its bare material texture if there are no graphics. "
		"Do not report a pass/fail judgment. Return JSON description string.",
		configured=configured,
		max_edge=1024,
		schema={
			"type": "object",
			"additionalProperties": False,
			"required": ["description"],
			"properties": {"description": {"type": "string", "minLength": 1}},
		},
	)
	description = str(observed.get("description") or "").strip()
	if not description:
		return {"description": "", "visibility": "unclear"}
	parsed = _parse_description(description, configured)

	quote = str(parsed.get("quote") or "").strip()
	if not quote or " ".join(quote.casefold().split()) not in " ".join(description.casefold().split()):
		return {"description": description, "visibility": "unclear", "unverified_extraction": parsed}
	return {**parsed, "description": description}


def sheet_marking_results(pictures, scene, *, configured=None, observe=None):
	scope = " ".join(
		str(scene.get(k) or "") for k in ("image_prompt", "generation_prompt", "authored_action")
	)
	if not sheet_material_instruction(scope):
		return []
	# Explicitly authored printed sheets are not blank-paper demonstrations.
	for match in re.finditer(
		r"\b(?:printed|illustrated|patterned|branded)\s+(?:paper|tissue|napkin|sheet)\b", scope, re.I
	):
		if not re.search(r"\b(?:no|not|without)\b", scope[max(0, match.start() - 25) : match.start()], re.I):
			return []
	observe = observe or observe_sheet
	indices = sorted({round(i * (len(pictures) - 1) / 4) for i in range(5)}) if pictures else []
	rows = []
	for index in indices:
		try:
			observation = observe(pictures[index], configured=configured)
		except Exception as exc:
			observation = {
				"visibility": "unclear",
				"description": "Sheet observation unavailable: " + type(exc).__name__,
			}
		marks, visibility = observation.get("printed_marks"), observation.get("visibility")
		valid = (
			visibility in {"visible", "absent"}
			and isinstance(marks, list)
			and not (visibility == "absent" and marks)
			and all(isinstance(mark, str) and bool(mark.strip()) for mark in marks)
		)
		verdict = "violated" if valid and marks else "supported" if valid else "uncertain"
		rows.append({**observation, "frame": index, "verdict": verdict})
	bad = [r for r in rows if r["verdict"] == "violated"]
	unknown = [r for r in rows if r["verdict"] == "uncertain"]
	return [
		{
			"id": "material.unauthored_sheet_print",
			"dimension": "identity",
			"claim": "The loose sheet carries no unauthored printed text, logo or illustration.",
			"verdict": "violated" if bad else "uncertain" if unknown or not rows else "supported",
			"frames": [r["frame"] for r in bad or unknown or rows],
			"reason": "; ".join(
				str(r.get("quote") or r.get("description") or "Sheet surface remains unverified.")
				for r in bad or unknown or rows
			)[:1000],
			"observations": rows,
		}
	]
