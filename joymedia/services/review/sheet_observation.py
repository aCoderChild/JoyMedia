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
		"natural folds, creases, shadows, the separate actor and anything printed on a package. Each "
		"mark has its own quote: the exact substring of the description that places that mark on the "
		"sheet. Use an empty list for an explicitly unmarked sheet or absent sheet, null if unclear. "
		"quote must be an exact supporting substring copied from the description. DESCRIPTION: "
		+ json.dumps(description)
	)
	schema = {
		"type": "object",
		"additionalProperties": False,
		"required": ["visibility", "printed_marks", "quote"],
		"properties": {
			"visibility": {"type": "string", "enum": ["visible", "absent", "unclear"]},
			"printed_marks": {
				"type": ["array", "null"],
				"items": {
					"type": "object",
					"additionalProperties": False,
					"required": ["mark", "quote"],
					"properties": {"mark": {"type": "string"}, "quote": {"type": "string"}},
				},
			},
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
	focused_asked = False
	if description and not _sheet_sentence(description):
		# A whole-image description often spends itself on the actor and never mentions a small sheet.
		description = f"{description} {_describe_sheet_only(picture, ask, configured)}".strip()
		focused_asked = True
	if not description:
		return {"description": "", "visibility": "unclear"}
	parsed = _parse_description(description, configured)

	result = _read_sheet(description, parsed)
	if result.get("visibility") != "unclear" or focused_asked:
		return result
	# A first look that stays unclear (a patterned rug read as the sheet) gets one look at the sheet alone.
	focused = _describe_sheet_only(picture, ask, configured)
	if not focused:
		return result
	return _read_sheet(focused, _parse_description(focused, configured))


def _read_sheet(description, parsed):
	"""The sheet observation an extracted description supports; unclear when it is not quoted or printing is not ruled out."""
	quote = str(parsed.get("quote") or "").strip()
	if not quote or not _quoted(quote, description):
		# The extractor often drops the quote although the description plainly describes the sheet
		# (48 rejected frames since 2026-10-20). Take the sheet's own sentence from the description in
		# code; it is trusted only when it describes no printing, or negates all it names.
		sentence = _sheet_sentence(description)
		if not sentence or parsed.get("printed_marks") or _unnegated_mark(sentence):
			return {"description": description, "visibility": "unclear", "unverified_extraction": parsed}
		return {"visibility": "visible", "printed_marks": [], "quote": sentence, "description": description}
	marks = parsed.get("printed_marks")
	if not isinstance(marks, list):
		return {**parsed, "description": description}
	on_sheet, elsewhere = [], []
	for row in marks:
		mark = str(row.get("mark") or "").strip() if isinstance(row, dict) else ""
		mark_quote = str(row.get("quote") or "").strip() if isinstance(row, dict) else ""
		if not mark or not mark_quote or not _quoted(mark_quote, description):
			return {"description": description, "visibility": "unclear", "unverified_extraction": parsed}
		(on_sheet if _places_on_sheet(mark_quote) else elsewhere).append(mark)
	# A package's printed artwork described near the sheet is not sheet print.
	return {
		**parsed,
		"printed_marks": on_sheet,
		**({"marks_not_on_sheet": elsewhere} if elsewhere else {}),
		"description": description,
	}


MARK_WORD = re.compile(
	r"\b(?:print\w*|logos?|letter\w*|text|words?|cartoons?|drawings?|illustrat\w*|patterns?|graphics?|"
	r"pictures?|images?|designs?|motifs?)\b",
	re.I,
)
NEGATION = re.compile(r"\b(?:no|not|without|free of|lacks?|lacking|devoid of|none)\b", re.I)


PACKAGE_WORD = re.compile(r"\b(?:box|pack(?:age|et)?|carton|container|dispenser|wrapper)s?\b", re.I)


def _sheet_sentence(description):
	"""The description's sentences about the loose sheet alone, joined; a package's own text is not the sheet's."""
	sentences = re.split(r"(?<=[.!?])\s+", description)
	return " ".join(s for s in sentences if SHEET_NOUN.search(s) and not PACKAGE_WORD.search(s)).strip()


def _unnegated_mark(sentence):
	"""Whether a sheet sentence names printing that no nearby negation rules out."""
	return any(
		not NEGATION.search(sentence[max(0, m.start() - 60) : m.start()])
		for m in MARK_WORD.finditer(sentence)
	)


def _describe_sheet_only(picture, ask, configured):
	"""A description of the loose sheet alone, apart from the character, any package and the floor."""
	focused = ask(
		picture,
		"Look only at the loose paper, tissue or napkin sheet in this image, not the character, not any "
		"package and not the rug or floor under it. Describe that sheet's surface: any colored shapes, "
		"drawings, logos or lettering, or its bare material if it has none. If no loose sheet is visible, "
		"say so. Return JSON description string.",
		configured=configured,
		max_edge=1024,
		schema={
			"type": "object",
			"additionalProperties": False,
			"required": ["description"],
			"properties": {"description": {"type": "string", "minLength": 1}},
		},
	)
	return str(focused.get("description") or "").strip()


def _quoted(quote, description):
	return " ".join(quote.casefold().split()) in " ".join(description.casefold().split())


PACKAGE_PHRASE = re.compile(
	r"(?:[\w'-]+\s+){0,4}\b(?:box|pack(?:age|et)?|carton|container|dispenser|wrapper)s?\b"
	r"(?:\s+of)?(?:\s+[\w'-]+){0,4}",
	re.I,
)
SHEET_NOUN = re.compile(r"\b(?:sheet|paper|tissue|napkin)s?\b", re.I)


def _places_on_sheet(quote):
	"""Whether a quote names the loose sheet itself, not only a package of it."""
	return bool(SHEET_NOUN.search(PACKAGE_PHRASE.sub(" ", quote)))


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
