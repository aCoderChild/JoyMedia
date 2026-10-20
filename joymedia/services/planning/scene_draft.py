"""Draft the scenes of a film from its brief, for a sheet that gives no scene table.

The structure is fixed, so the result is predictable: one Hook, one scene per USP, one Outro. Timing is shared out of the
total length. The language model only writes each scene's visual, action, voice-over, sound and on-screen text in the
brief's own language, from the brief alone; its answer is checked (right number of scenes, an action each, only the listed
characters) and when it is missing or wrong the scenes get plain text built from the brief, never invented claims.
"""

from __future__ import annotations

import re
import unicodedata

from joymedia.services.planning.workbook import character_names, parse_duration_seconds, usp_points

DEFAULT_TOTAL_SECONDS = 30.0
MAX_SCENES = 12


def scene_plan(metadata: dict) -> list[dict]:
	"""The beats of the film: [{beat_name, kind, usp}] with a Hook, a scene per USP and an Outro."""
	usps = usp_points(metadata)[: MAX_SCENES - 2]
	beats = [{"beat_name": "Hook", "kind": "hook", "usp": ""}]
	beats += [{"beat_name": f"USP {number}", "kind": "usp", "usp": usp} for number, usp in enumerate(usps, 1)]
	beats.append({"beat_name": "Outro", "kind": "outro", "usp": ""})
	return beats


def shares(count: int, total: float) -> list[float]:
	"""Seconds per scene: the Hook and Outro get 15% each (at least 3 s), the USP scenes share the rest."""
	if count <= 2:
		return [round(total / count, 2)] * count
	edge = max(3.0, round(total * 0.15, 2))
	middle = max(2.0, round((total - 2 * edge) / (count - 2), 2))
	return [edge] + [middle] * (count - 2) + [edge]


def draft_scenes(
	metadata: dict, lang_is_english: bool = False, use_model: bool = True, brand: dict | None = None
) -> list[dict]:
	"""Scenes shaped like the ones a sheet's table gives, ready to become Shots."""
	total = parse_duration_seconds(metadata.get("duration", "")) or DEFAULT_TOTAL_SECONDS
	beats = scene_plan(metadata)
	written = _written_by_model(metadata, beats, brand or {}) if use_model else None
	texts = written or [_plain_text(metadata, beat, lang_is_english) for beat in beats]
	cursor, scenes = 0.0, []
	for number, (beat, length, text) in enumerate(
		zip(beats, shares(len(beats), total), texts, strict=False), 1
	):
		start, end = cursor, round(cursor + length, 3)
		cursor = end
		scenes.append(
			{
				"source_row": number,
				"beat_name": text.get("beat_name") or beat["beat_name"],
				"source_timing": _clock(start, end),
				"start_seconds": start,
				"end_seconds": end,
				"duration_seconds": round(end - start, 3),
				"timing_source": "drafted",
				"visual_camera": text.get("visual_camera", ""),
				"action": text["action"],
				"voice_over": text.get("voice_over", ""),
				"audio_cues": text.get("audio_cues", ""),
				"on_screen_text": text.get("on_screen_text", ""),
				"illustration_reference": "",
				"continuity_mode": "New Scene",
			}
		)
	return scenes


def _clock(start, end):
	def fmt(value):
		return f"{int(value // 60)}:{int(value % 60):02d}"

	return f"{fmt(start)} - {fmt(end)}"


def _plain_text(metadata, beat, english):
	"""Scene text built from the brief alone: no invented story, only what the brief says."""
	cast = [person["name"] for person in character_names(metadata)]
	lead = next((p["name"] for p in character_names(metadata) if p["main"]), cast[0] if cast else "")
	product = metadata.get("product_name", "")
	who = lead or (cast[0] if cast else ("the characters" if english else "các nhân vật"))
	if beat["kind"] == "hook":
		return {
			"action": f"{who} meet the everyday problem that {product} solves."
			if english
			else f"{who} gặp tình huống quen thuộc mà {product} giải quyết.",
			"visual_camera": "Close-up" if english else "Cận cảnh",
		}
	if beat["kind"] == "usp":
		return {
			"action": f"{who} show clearly: {beat['usp']}."
			if english
			else f"{who} thể hiện rõ: {beat['usp']}.",
			"on_screen_text": beat["usp"][:60],
		}
	return {
		"action": f"{who} with {product} in the centre of the frame."
		if english
		else f"{who} cùng {product} ở chính giữa khung hình.",
		"visual_camera": "Eye-level" if english else "Trung cảnh chính diện",
	}


def _written_by_model(metadata, beats, brand=None):
	"""One text per beat from the language model, or None when it is unavailable or its answer does not check out."""
	from joymedia.services.planning.director_rules import CINEMATOGRAPHY_RULES
	from joymedia.services.planning.production import _ask_planner

	cast = [person["name"] for person in character_names(metadata)]
	lines = "\n".join(
		f"{n}. {b['beat_name']}" + (f" — selling point: {b['usp']}" if b["usp"] else "")
		for n, b in enumerate(beats, 1)
	)
	prompt = (
		"Write the scenes of a short advertisement from this brief. Write in the SAME LANGUAGE as the brief.\n"
		f"PRODUCT: {metadata.get('product_name', '')}\nOBJECTIVE: {metadata.get('objective', '')}\n"
		f"TONE: {metadata.get('tone_mood', '')}\nCHARACTERS (use only these, by these names): {', '.join(cast) or 'none'}\n"
		+ "".join(
			f"{title}: {(brand or {})[key]}\n"
			for key, title in (
				("key_message", "KEY MESSAGE"),
				("claims", "APPROVED CLAIMS (use only these)"),
				("avoid", "MUST NOT SAY OR SHOW"),
			)
			if (brand or {}).get(key)
		)
		+ f"SCENES (exactly {len(beats)}, in this order):\n{lines}\n"
		"Every scene must show the characters using or showing the PRODUCT itself, and each selling-point scene must show "
		"that selling point happening with the product. Use only objects, food and places that the brief or the product "
		"implies; never add others. "
		"For each scene give: visual_camera (setting and shot), action (one or two sentences: who does what), "
		"voice_over (one short spoken line, or empty), audio_cues (a sound effect starting with 'SFX:', or empty), "
		"on_screen_text (a short caption, or empty). Do not invent claims, prices or facts that are not in the brief. "
		+ CINEMATOGRAPHY_RULES
		+ "\n"
		+ 'Return {"scenes":[{"visual_camera":"","action":"","voice_over":"","audio_cues":"","on_screen_text":""}]}'
	)
	try:
		raw = _ask_planner(
			prompt, system="You write advertising storyboards. Return JSON only.", max_tokens=1800
		)
	except Exception:  # a planner that is down is reported by the caller's own flow; drafting falls back
		return None
	rows = (raw or {}).get("scenes") if isinstance(raw, dict) else None
	if not isinstance(rows, list) or len(rows) != len(beats):
		return None
	texts = []
	anchors = _words(f"{metadata.get('product_name', '')} {metadata.get('objective', '')}")
	for beat, row in zip(beats, rows, strict=False):
		if not isinstance(row, dict) or not str(row.get("action") or "").strip():
			return None
		text = {
			key: re.sub(r"\s+", " ", str(row.get(key) or "")).strip()
			for key in ("visual_camera", "action", "voice_over", "audio_cues", "on_screen_text")
		}
		# A scene that never touches the product (or, for a selling point, that point) is the model drifting off-brief.
		said = _words(" ".join(text.values()))
		if not said & (
			_words(f"{beat['usp']} {metadata.get('product_name', '')}")
			if beat["usp"]
			else anchors | _words(metadata.get("product_name", ""))
		):
			return None
		texts.append(text)
	return texts


def _words(text):
	"""Accent-insensitive words of 4+ letters, for checking that a scene is about the brief."""
	plain = unicodedata.normalize("NFKD", str(text).casefold()).replace("đ", "d")
	return {
		word for word in re.findall(r"[a-z]{4,}", "".join(c for c in plain if not unicodedata.combining(c)))
	}
