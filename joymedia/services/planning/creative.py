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
		"Create an original, brisk product commercial from these references, not a slideshow. "
		"Invent a coherent situation with a visible cause, reaction, product acquisition/use and visible result. "
		"Supply every prerequisite action before its consequence: acquire, grip, move into contact, perform the use, reveal the changed state. Reaching for a container is not obtaining its contents: show removal before using the item. "
		"Split distinct interactions into motivated shots; preserve object states, supports, screen direction and anatomy across cuts. "
		"Each non-final scene must advance a concrete subject action, not waiting, approaching alone, posing or camera motion. "
		"Perform gestures promptly in real time; use several purposeful actions across the film. "
		"Write timed Action phases that start at 0 and end exactly at that scene duration, with no gaps. "
		"Example syntax for a five-second scene: [0-2s] one visible action\n[2-5s] its consequence. "
		"Only supplied reference keys may appear in cast/products. Gallery views are one identity, not additional cast. "
		"Reference observations supply action rhythms, never additional actors, products, claims or sounds. "
		"Only state supplied approved claims. Ordinary props and a coherent location may be invented, but name them before use. "
		"Vary adjacent shot sizes with purpose; preserve the action axis; show the product close at use and clearly at the end. "
		"Camera behavior is derived later from semantic stage/framing: do not put camera moves in Action. "
		"Use layered depth, shaped directional lighting, material texture and a deliberate palette. "
		"Choose developing rhythmic music aligned with action, event-linked sounds and a resolved ending. "
		"Preserve explicit format/duration. If absent, propose suitable ones with rationale, never default to reels. "
		"Return the complete schema with 2–12 scenes, totaling at most sixty seconds. "
		"Keep visual/continuity/state fields concise; scene voiceover may be empty. "
		"Generate a different premise/action chain from prior concepts.\nCONSTRAINTS: "
		+ json.dumps(constraints, ensure_ascii=False)
		+ "\nREFERENCE KEY ROSTER: "
		+ json.dumps(roster, ensure_ascii=False)
		+ "\nSAMPLED ACTION OBSERVATIONS: "
		+ json.dumps(observations, ensure_ascii=False)
		+ "\nPRIOR CONCEPTS: "
		+ json.dumps(list(previous), ensure_ascii=False)
		+ "\nVARIATION ID: "
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
			script = validate_script(result, inventory, constraints)
			findings = review_script_actions(script)
			issues = [r for r in findings if not all(r[k] for k in ("progresses", "causal", "paced"))]
			if issues:
				raise ValueError(
					"Action review: "
					+ json.dumps(issues, ensure_ascii=False)
					+ "\nRevise this rejected action chain: "
					+ json.dumps(
						[{k: s[k] for k in ("duration_seconds", "action")} for s in script["scenes"]]
					)
				)
			script["action_review"] = findings
			return script
		except ValueError as exc:
			error += (
				f"\nRepair attempt {_attempt + 1}; return the complete script, correcting ALL accumulated errors: "
				+ str(exc)
			)
	raise ValueError("Automatic script remained invalid after bounded repair: " + error)


def review_script_actions(script):
	"""Second-pass script compliance through the existing configured writer runtime.

	This reviews the script, not rendered physical correctness or release eligibility.
	"""
	from joymedia.services.planning.production import _ask_planner

	count = len(script["scenes"])
	item = {
		"type": "object",
		"properties": {
			"scene": {"type": "integer", "minimum": 1, "maximum": count},
			"progresses": {"type": "boolean"},
			"causal": {"type": "boolean"},
			"paced": {"type": "boolean"},
			"reason": {"type": "string", "maxLength": 240},
		},
		"required": ["scene", "progresses", "causal", "paced", "reason"],
		"additionalProperties": False,
	}
	schema = {
		"type": "object",
		"properties": {"findings": {"type": "array", "items": item, "minItems": count, "maxItems": count}},
		"required": ["findings"],
		"additionalProperties": False,
	}
	draft = [
		{
			k: scene[k]
			for k in ("duration_seconds", "visual_camera", "action", "visible_change", "cast", "products")
		}
		for scene in script["scenes"]
	]
	result = _ask_planner(
		"Review every scene of this brisk commercial strictly. Return one finding per scene in order. "
		"progresses: a concrete subject action changes an object/state; camera motion, a hero-shot label, posing or approaching alone do not count. Only the FINAL scene may use a product hold. "
		"causal: every object/tool is visibly acquired before use, required contact precedes a resulting change, no skipped prerequisite or reset between shots, no contradictory opening/action. Reaching/holding a container does NOT acquire its contents: later use of an item without its removal is causal=false. "
		"paced: allocated time supports active real-time action. A shot spent entirely just reaching, leaning or looking is NOT brisk pacing. The final hold must not consume a disproportionate share of this action-led film. "
		"Reason must cite the specific action text or missing prerequisite; never accept generic claims of realism. "
		"This is script review only, not evidence of rendered physics.\n"
		+ json.dumps(draft, ensure_ascii=False),
		system="You are the strict second-pass commercial storyboard compliance editor. Return only JSON.",
		capability="writer",
		sampling_profile="creative_script_review",
		response_schema=schema,
	)
	rows = result.get("findings", [])
	if (
		len(rows) != count
		or [r.get("scene") for r in rows] != list(range(1, count + 1))
		or any(type(r.get(k)) is not bool for r in rows for k in ("progresses", "causal", "paced"))
	):
		raise ValueError("Script action review did not cover each scene exactly once.")
	return rows


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
