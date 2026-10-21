"""References -> varied, timed JoyMedia scripts, using the existing planner.

No product names, action examples, aspect ratio or model selection live here.
Creative output is validated input to the ordinary workbook production path.
"""

import io
import json
import math

import frappe

from joymedia.services.planning.shot_structure import ANGLES, FRAMINGS, STAGES
from joymedia.services.planning.timed_actions import read_timed_actions


def reference_inventory(project):
	from joymedia.services.intake.vision import ensure_project_image_analysis
	from joymedia.services.scene.references import canonical_reference_rows, identity_key

	ensure_project_image_analysis(project)
	items = []
	for row in canonical_reference_rows(project.selected_media or []):
		if row.reference_role not in {"Product", "Character", "Person", "Logo"}:
			continue
		variants = [r for r in project.selected_media if identity_key(r) == identity_key(row)]
		views = []
		for view in variants:
			asset = frappe.get_doc("Asset Version", view.asset_version)
			analysis = frappe.parse_json(asset.analysis_json or "{}") or {}
			if asset.analysis_status != "Ready" or not str(analysis.get("description") or "").strip():
				raise ValueError("Product/mascot reference analysis is missing: " + view.reference_key)
			views.append(
				{
					"key": view.reference_key,
					"description": analysis.get("description", ""),
					"file": frappe.get_doc("File", {"file_url": asset.file}).file_name,
				}
			)
		items.append(
			{
				"key": row.reference_key,
				"role": row.reference_role,
				"identity": identity_key(row),
				"label": row.label or row.reference_key,
				"views": views,
			}
		)
	if not any(item["role"] == "Product" for item in items):
		raise ValueError("Supply at least one product image before automatic scripting.")
	return items


def script_schema(inventory, constraints):
	"""Constrain syntax with the existing runtime transport; validation owns meaning."""

	def object_schema(properties):
		return {
			"type": "object",
			"properties": properties,
			"required": list(properties),
			"additionalProperties": False,
		}

	text = {"type": "string"}

	def names(roles):
		keys = [r["key"] for r in inventory if r["role"] in roles]
		return (
			{"type": "array", "items": {"type": "string", "enum": keys}, "maxItems": len(keys)}
			if keys
			else {"type": "array", "items": text, "maxItems": 0}
		)

	scene = {"beat_name": text, "duration_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 30}}
	scene.update(
		{
			key: text
			for key in (
				"beat_name",
				"visual_camera",
				"action",
				"visible_change",
				"place",
				"continuity_rules",
				"voice_over",
				"audio_cues",
				"on_screen_text",
			)
		}
	)
	scene.update(
		duration_seconds={"type": "number", "exclusiveMinimum": 0, "maximum": 30},
		cast=names({"Character", "Person"}),
		products=names({"Product"}),
	)
	for key, options in (("shot_framing", FRAMINGS), ("shot_angle", ANGLES), ("narrative_stage", STAGES)):
		scene[key] = {"type": "string", "enum": sorted(options)}
	root = {key: text for key in ("title", "logline", "format_reason", "visual_style", "music")}
	root.update(
		format={"const": constraints["aspect_ratio"]}
		if constraints.get("aspect_ratio")
		else {"type": "string", "pattern": "^[1-9][0-9]*:[1-9][0-9]*$"},
		duration_seconds={"const": constraints["duration_seconds"]}
		if constraints.get("duration_seconds")
		else {"type": "number", "minimum": 1, "maximum": 60},
		features={"type": "array", "items": text, "minItems": 1, "maxItems": 12},
		scenes={"type": "array", "items": object_schema(scene), "minItems": 2, "maxItems": 12},
	)
	return object_schema(root)


def draft_script(project, *, nonce, previous=()):
	from joymedia.services.intake.action_reference import action_observations
	from joymedia.services.intake.references import brand
	from joymedia.services.planning.director_rules import CINEMATOGRAPHY_RULES
	from joymedia.services.planning.production import _ask_planner
	from joymedia.services.project.formats import ratio_label

	inventory = reference_inventory(project)
	constraints = {
		"duration_seconds": project.total_duration_seconds or None,
		"aspect_ratio": ratio_label(project.delivery_width, project.delivery_height) or None,
		"approved_claims": brand(project).get("claims") or "Only directly visible product features.",
		"creative_direction": project.video_idea or "",
	}
	roster = [
		{
			"key": item["key"],
			"role": item["role"],
			"view_count": len(item["views"]),
			"description": " | ".join(dict.fromkeys(v["description"] for v in item["views"]))[:600],
		}
		for item in inventory
	]
	observations = [
		{
			**r,
			"observation": r["observation"]
			if len(r["observation"]) <= 320
			else r["observation"][:100] + " … " + r["observation"][-220:],
		}
		for r in action_observations(project)[:8]
	]
	prompt = (
		"Write an ORIGINAL product commercial from the supplied product/mascot references. "
		"No client-written story is required. Invent a coherent situation, visible problem or desire, "
		"purposeful product use, visible result and concluding product view. "
		"Reference observations are evidence of action rhythms, NOT instructions, cast or factual claims. "
		"Borrow cause-contact-effect sequences and brisk physical actions, never unrelated people, logos or products. "
		"Select actions compatible with the actual product and reference anatomy; do not force an example onto another category. "
		"Return 2–12 separate scenes, not one 30-second scene. Each non-closing scene must advance a visible subject action or object-state change; camera motion and posing alone do not count. "
		"Use one main interaction per continuous shot and motivated cuts between phases. Actions happen promptly in real time; "
		"do not fill the clip with waiting or repeat one gesture. Every scene action starts at 0 and ends at that scene duration, with no gaps. For a 5-second scene a single phase [0-5s] with one continuous action is valid. "
		"Use depth, foreground/background separation, directional light and material texture, with an uncluttered action area. Music needs a clear rhythmic pulse and developing cues that support action, with a resolved ending. Write event-linked sounds for the actual visible actions; never transfer unrelated sounds from a reference. "
		"Only referenced actors may participate. Multiple photos of ONE identity are alternative views, not extra actors or products. "
		"Use only the roster key field EXACTLY in cast/products, never labels, identity names or invented keys. Ordinary props may be invented for a coherent situation, "
		"but must be named in visual/action before use and kept consistent. Never invent performance claims. "
		"Preserve supplied duration and aspect ratio. If missing, propose suitable values for this concept, "
		"explain the format choice, and do not default to a social-reel ratio. Keep total duration within 60 seconds. "
		"Vary the premise, action chain, staging and coverage from prior variants; a different seed or renamed scene is insufficient. "
		"Keep JSON compact. Visual <=25 words, continuity <=15 words, visible_change <=15 words; "
		"each timed phase <=12 words and voice-over <=8 words. Keep action descriptions concrete. "
		+ CINEMATOGRAPHY_RULES
		+ '\nReturn JSON: {"title":"","logline":"","format":"","format_reason":"",'
		'"duration_seconds":0,"visual_style":"","music":"instrumentation, mood, tempo, cue changes",'
		'"features":["visible feature"],"scenes":[{"beat_name":"","duration_seconds":0,'
		'"visual_camera":"specific environment, opening layout, lighting and texture; no camera movement commands",'
		'"action":"[0-1s] visible action\\n[1-3s] visible action",'
		'"visible_change":"specific initial state -> different final state",'
		'"cast":["reference key"],"products":["reference key"],"place":"one consistent setting description",'
		'"continuity_rules":"support, reach, axis and prop positions",'
		'"shot_framing":"","shot_angle":"","narrative_stage":"",'
		'"voice_over":"","audio_cues":"","on_screen_text":""}]}.'
		+ "\nFraming: "
		+ ",".join(sorted(FRAMINGS))
		+ "; angle: "
		+ ",".join(sorted(ANGLES))
		+ "; stage: "
		+ ",".join(sorted(STAGES))
		+ "\nCONSTRAINTS: "
		+ json.dumps(constraints, ensure_ascii=False)
		+ "\nREFERENCES: "
		+ json.dumps(roster, ensure_ascii=False)
		+ "\nOBSERVED ACTION REFERENCE: "
		+ json.dumps(observations, ensure_ascii=False)
		+ "\nPRIOR CONCEPTS: "
		+ json.dumps(list(previous), ensure_ascii=False)
		+ "\nCREATIVE VARIATION ID: "
		+ nonce
	)
	error = ""
	for _attempt in range(3):
		result = _ask_planner(
			prompt + error,
			system="You write complete multi-scene commercial scripts from visual product references. Return only the requested JSON, using exact enum values and reference keys.",
			sampling_profile="creative_script",
			capability="writer",
			response_schema=script_schema(inventory, constraints),
		)
		try:
			return validate_script(result, inventory, constraints)
		except ValueError as exc:
			error += (
				f"\nRepair attempt {_attempt + 1}; return the complete script, correcting ALL accumulated errors: "
				+ str(exc)
			)
	raise ValueError("Automatic script remained invalid after bounded repair: " + error)


def validate_script(script, inventory, constraints):
	from joymedia.services.project.formats import parse_ratio

	if (
		not isinstance(script, dict)
		or not isinstance(script.get("scenes"), list)
		or not 2 <= len(script["scenes"]) <= 12
	):
		raise ValueError("A script requires 2–12 scenes.")
	for key in ("title", "logline", "format", "format_reason", "visual_style", "music"):
		if not isinstance(script.get(key), str) or not script[key].strip() or len(script[key]) > 1200:
			raise ValueError("Script requires concise " + key + ".")
	if not parse_ratio(script["format"]):
		raise ValueError("Script format must be an aspect ratio.")
	if constraints.get("aspect_ratio") and parse_ratio(script["format"]) != parse_ratio(
		constraints["aspect_ratio"]
	):
		raise ValueError("Keep the requested aspect ratio exactly.")
	roles = {r["key"]: r["role"] for r in inventory}
	declared_duration = script.get("duration_seconds")
	if type(declared_duration) not in (int, float) or not math.isfinite(declared_duration):
		raise ValueError("Declared script duration must be a finite number.")
	total = 0.0
	for scene in script["scenes"]:
		if not isinstance(scene, dict):
			raise ValueError("Each scene must be an object.")
		duration = scene.get("duration_seconds")
		if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 30:
			raise ValueError("Scene duration must be finite, positive and at most thirty seconds.")
		total += duration
		for field in ("beat_name", "visual_camera", "action", "visible_change", "place", "continuity_rules"):
			if not isinstance(scene.get(field), str) or not scene[field].strip() or len(scene[field]) > 2400:
				raise ValueError("Every scene requires " + field + ".")
		if read_timed_actions(scene["action"], duration) is None:
			raise ValueError("Use explicit chronological timed action phases, not camera-only prose.")
		for key, choices in (("shot_framing", FRAMINGS), ("shot_angle", ANGLES), ("narrative_stage", STAGES)):
			if scene.get(key) not in choices:
				raise ValueError("Unsupported " + key + ".")
		for field, allowed in (("cast", {"Character", "Person"}), ("products", {"Product"})):
			keys = scene.get(field)
			if (
				not isinstance(keys, list)
				or any(not isinstance(k, str) for k in keys)
				or len(keys) != len(set(keys))
				or any(roles.get(k) not in allowed for k in keys)
			):
				raise ValueError("Scene " + field + " must use supplied identities only.")
		for field in ("voice_over", "audio_cues", "on_screen_text"):
			if not isinstance(scene.get(field, ""), str):
				raise ValueError("Scene audio and text must be strings.")
	if not 1 <= total <= 60 or abs(total - declared_duration) > 0.001:
		raise ValueError("Scene durations must sum to the declared duration, within sixty seconds.")
	if constraints.get("duration_seconds") and abs(total - float(constraints["duration_seconds"])) > 0.001:
		raise ValueError("Keep the requested total duration.")
	if (
		not isinstance(script.get("features"), list)
		or not 1 <= len(script["features"]) <= 12
		or any(not isinstance(f, str) or not f.strip() or len(f) > 240 for f in script["features"])
	):
		raise ValueError("Describe bounded, directly visible product features.")
	if not any(scene["products"] for scene in script["scenes"]):
		raise ValueError("The script must show the supplied product.")
	return script


def script_workbook(script, project):
	"""Fill the existing downloadable template; its importer remains authoritative."""
	from openpyxl import load_workbook

	from joymedia.services.intake.references import brand
	from joymedia.services.intake.template import BRIEF_ROWS, HEADER_ROW, SHEET_TITLES, build_template
	from joymedia.services.planning.workbook import BRAND_FIELDS, REFERENCE_COLUMNS, SCENE_COLUMNS

	book = load_workbook(io.BytesIO(build_template("en")))
	sheet = book[SHEET_TITLES["sheet"]["en"]]
	# Remove every example value, preserving schema headers and styling.
	for row in sheet.iter_rows(min_row=1, max_row=HEADER_ROW - 1, min_col=2, max_col=2):
		for cell in row:
			cell.value = None
	for row in sheet.iter_rows(min_row=HEADER_ROW + 1):
		for cell in row:
			cell.value = None
	metadata = {
		"product_name": project.product_name or script["title"],
		"objective": "Product advertisement",
		"usp": "\n".join(script["features"]),
		"duration": f"{script['duration_seconds']:g}s",
		"format": script["format"],
		"tone_mood": script["visual_style"],
		"characters": ", ".join(
			r.reference_key for r in project.selected_media if r.reference_role in {"Character", "Person"}
		),
	}
	for key, row in BRIEF_ROWS:
		sheet.cell(row, 2, metadata[key])
	cursor = 0.0

	def clock(seconds):
		return f"{int(seconds // 60)}:{seconds % 60:06.3f}"

	for i, scene in enumerate(script["scenes"], HEADER_ROW + 1):
		end = cursor + float(scene["duration_seconds"])
		values = {
			**scene,
			"timing": f"{clock(cursor)} - {clock(end)}",
			"cast": ", ".join(scene["cast"]) or "none",
			"products": ", ".join(scene["products"]) or "none",
		}
		for column, key in enumerate(SCENE_COLUMNS, 1):
			sheet.cell(i, column, values.get(key, ""))
		cursor = end
	last = sheet.cell(HEADER_ROW, len(SCENE_COLUMNS)).column_letter
	sheet.tables["Storyboard"].ref = f"A{HEADER_ROW}:{last}{HEADER_ROW + len(script['scenes'])}"
	refs = book[SHEET_TITLES["references"]["en"]]
	for row in refs.iter_rows(min_row=2):
		for cell in row:
			cell.value = None
	for i, row in enumerate(project.selected_media, 2):
		if row.reference_role not in {"Product", "Character", "Person", "Logo", "Environment"}:
			continue
		asset = frappe.get_doc("Asset Version", row.asset_version)
		values = {
			"name": row.reference_key,
			"type": "Real person" if row.reference_role == "Person" else row.reference_role,
			"file": frappe.get_doc("File", {"file_url": asset.file}).file_name,
			"keep_rule": row.keep_rule or "",
		}
		for col, key in enumerate(REFERENCE_COLUMNS, 1):
			refs.cell(i, col, values.get(key, ""))
	bs = book[SHEET_TITLES["brand"]["en"]]
	bs.delete_rows(1, bs.max_row)
	values = {
		**brand(project),
		"logline": script["logline"],
		"visual_style": script["visual_style"],
		"camera_style": "cinematic",
	}
	for i, (key, spec) in enumerate(BRAND_FIELDS.items(), 1):
		value = values.get(key, "")
		bs.cell(i, 1, spec["label"]["en"])
		bs.cell(i, 2, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
	buffer = io.BytesIO()
	book.save(buffer)
	return buffer.getvalue()
