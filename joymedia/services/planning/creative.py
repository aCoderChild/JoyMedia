"""References -> varied, timed JoyMedia scripts, using the existing planner.

No product names, action examples, aspect ratio or model selection live here.
Creative output is validated input to the ordinary workbook production path.
"""

import io
import json
import math

import frappe

from joymedia.services.planning.script_review import review_script_actions
from joymedia.services.planning.shot_structure import ANGLES, FRAMINGS, MOTIONS, STAGES
from joymedia.services.planning.timed_actions import normalize_action_separators, read_timed_actions

CREATIVE_INVARIANTS = (
	"Preserve reference identities, observed product construction, explicit format/duration and approved claims. "
	"Keep one coherent interaction per shot, chronological prerequisites and persistent object/support states. "
	"Invent no opening mechanism. Extracted consumables remain outside their unused stock; do not reset the story by putting them back. "
	"Name every ordinary prop and action target before use. Non-final shots advance tangible object/action state, not prolonged looking or posing. "
	"A real change of material form, object location or contact is tangible progress. The final branded presentation may hold briefly. "
	"Use purposeful coverage and action-driven phase timings, with camera behavior derived from semantic structure."
)


def reference_inventory(project):
	from joymedia.services.intake.vision import ensure_project_image_analysis
	from joymedia.services.scene.references import canonical_reference_rows, identity_key

	ensure_project_image_analysis(project)
	items = []
	for row in canonical_reference_rows(project.selected_media or []):
		if row.reference_role not in {"Product", "Character", "Person", "Logo", "Environment"}:
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
				"keep_rule": row.keep_rule or "",
				"label": row.label or row.reference_key,
				"views": views,
			}
		)
	if not any(item["role"] == "Product" for item in items):
		raise ValueError("Supply at least one product image before automatic scripting.")
	return items


def reference_choices(inventory):
	"""Alternative image keys resolve to one identity, never additional cast."""
	return {
		view.get("key", item["key"]): {"role": item["role"], "identity": item.get("identity") or item["key"]}
		for item in inventory
		for view in item.get("views") or [{"key": item["key"]}]
	}


def script_schema(inventory, constraints):
	"""Constrain syntax with the existing runtime transport; validation owns meaning."""

	def object_schema(properties):
		return {
			"type": "object",
			"properties": properties,
			"required": list(properties),
			"additionalProperties": False,
		}

	text = {"type": "string", "minLength": 1}

	def names(roles):
		choices = {
			key: value for key, value in reference_choices(inventory).items() if value["role"] in roles
		}
		keys = list(choices)
		return (
			{
				"type": "array",
				"items": {"type": "string", "enum": keys},
				"maxItems": len({value["identity"] for value in choices.values()}),
			}
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
	scene["action"] = {
		"type": "string",
		"pattern": r"^\[[0-9]+(?:\.[0-9]+)?-[0-9]+(?:\.[0-9]+)?s\] [\s\S]+$",
		"description": "Timed, tangible subject actions in order within one coherent interaction. Separate travel, acquisition and use into different shots. No camera or on-screen text commands here.",
	}
	scene["visual_camera"] = {
		**text,
		"description": "One opening composition before the first timed action, with environment and subject placement. Do not describe a later result or camera movement.",
	}
	scene["visible_change"] = {
		**text,
		"description": "The observable end-state change caused by this shot's actions, after their prerequisites.",
	}
	for key in ("voice_over", "audio_cues", "on_screen_text"):
		scene[key] = {"type": "string"}
	scene["audio_cues"].update(
		pattern=r"^(?:(?:SFX|BGM):[^\n]+(?:\n|$))*$",
		description="Native audio cue lines: SFX: physical sounds caused by visible actions; optional BGM: score cue change. One labelled cue per line, or empty. Dialogue belongs in voice_over; the continuous score is described in music.",
	)
	for key, options in (("shot_framing", FRAMINGS), ("shot_angle", ANGLES), ("narrative_stage", STAGES)):
		scene[key] = {"type": "string", "enum": sorted(options)}
	scene["subject_motion"] = {
		"type": "string",
		"enum": sorted(MOTIONS),
		"description": "Locomotion when the subject's whole body travels through the setting, including walking while carrying. Manipulation for object handling in place; stationary for no subject movement. Body travel takes priority over incidental hand gestures.",
	}
	scene["narrative_stage"]["description"] = (
		"Dominant narrative job, not a generic scene label: establish=opening geography; "
		"approach=travel toward target; grip=take hold; extract=remove contents; unfold=open material; "
		"detail=demonstrate contact/function; inspect=examine result; present=show product; "
		"feel=brief reaction; hero=final branded presentation."
	)
	root = {key: text for key in ("title", "logline", "format_reason", "visual_style", "music")}
	root["visual_style"] = {
		**text,
		"description": "Art direction only: rendering style, lighting, material finish, palette and mood. Camera movement belongs to shot structure, never this field.",
	}
	root["music"] = {
		**text,
		"description": "Instrumentation, mood, tempo and cue changes aligned with the story, with a resolved ending.",
	}
	minimum_scenes = (
		max(
			2,
			math.ceil(
				constraints.get("duration_seconds", 0)
				* constraints.get("fps", 24)
				/ constraints["max_scene_frames"]
			),
		)
		if constraints.get("duration_seconds") and constraints.get("max_scene_frames")
		else 2
	)
	if minimum_scenes > 12:
		raise ValueError("The requested duration exceeds this workflow's automatic storyboard scene budget.")
	root.update(
		format={"const": constraints["aspect_ratio"]}
		if constraints.get("aspect_ratio")
		else {"type": "string", "pattern": "^[1-9][0-9]*:[1-9][0-9]*$"},
		duration_seconds={"const": constraints["duration_seconds"]}
		if constraints.get("duration_seconds")
		else {"type": "number", "minimum": 1, "maximum": 60},
		features={"type": "array", "items": text, "minItems": 1, "maxItems": 12},
		scenes={"type": "array", "items": object_schema(scene), "minItems": minimum_scenes, "maxItems": 12},
	)
	return object_schema(root)


def fit_generated_timing(script, total_seconds, fps, *, max_scene_frames=None):
	"""Compile AI timing proposals through the existing frame/interval engines.

	Only automatic drafts call this; an imported authored workbook is never retimed.
	"""
	from joymedia.services.planning.durations import allocate_frames
	from joymedia.services.planning.plan_parsing import _rescale_motion_plan

	if (
		not isinstance(script, dict)
		or not isinstance(script.get("scenes"), list)
		or not 2 <= len(script["scenes"]) <= 12
	):
		raise ValueError("A script requires 2–12 scenes.")
	proposals, weights, actions = [], [], []
	for scene in script["scenes"]:
		if not isinstance(scene, dict) or type(scene.get("duration_seconds")) not in (int, float):
			raise ValueError("Each proposed scene requires a numeric timing weight.")
		weights.append(scene["duration_seconds"])
		parsed = read_timed_actions(scene.get("action"))
		if not parsed:
			raise ValueError("Each proposed scene needs explicit chronological timed actions.")
		proposals.append({"duration_seconds": scene["duration_seconds"], "action": scene["action"]})
		actions.append(parsed)
	total = total_seconds or script.get("duration_seconds")
	if type(total) not in (int, float) or not math.isfinite(total) or not 1 <= total <= 60:
		raise ValueError("Requested duration must be within sixty seconds.")
	frames = allocate_frames(weights, round(total * fps), maximum=max_scene_frames)
	for scene, phases, count in zip(script["scenes"], actions, frames, strict=True):
		plan = {"duration_seconds": count / fps, "motion_plan": {"actions": phases}}
		_rescale_motion_plan(plan, phases[-1]["end"])
		scene["duration_seconds"] = count / fps

		def timestamp(value):
			return f"{value:.9f}".rstrip("0").rstrip(".")

		scene["action"] = "\n".join(
			f"[{timestamp(row['start'])}-{timestamp(row['end'])}s] {row['action']}" for row in phases
		)
	script["duration_seconds"] = sum(frames) / fps
	script["timing_compilation"] = {
		"requested_seconds": total,
		"fps": fps,
		"scene_frames": frames,
		"proposals": proposals,
	}
	return script


def draft_script(project, *, nonce, previous=(), review_notes=()):
	from joymedia.services.intake.action_reference import action_observations
	from joymedia.services.intake.references import brand
	from joymedia.services.planning.camera import reference_camera_grammar
	from joymedia.services.planning.durations import _timeline_fps
	from joymedia.services.planning.production import _ask_planner
	from joymedia.services.project.formats import ratio_label

	inventory = reference_inventory(project)
	from joymedia.services.workflows.capabilities import capacity

	workflow = frappe.get_doc("Generation Workflow", project.workflow) if project.get("workflow") else None
	fps = _timeline_fps(
		frappe._dict(
			output_fps=frappe.db.get_value("Generation Workflow", project.workflow, "output_fps")
			if project.get("workflow")
			else 0
		)
	)
	camera_grammar = reference_camera_grammar(project) or {}
	constraints = {
		"duration_seconds": project.total_duration_seconds or None,
		"fps": fps,
		"max_scene_frames": capacity(workflow)
		if workflow and not workflow.get("continuation_workflow")
		else None,
		"aspect_ratio": ratio_label(project.delivery_width, project.delivery_height) or None,
		"approved_claims": brand(project).get("claims") or "Only directly visible product features.",
		"avoid": brand(project).get("avoid") or "",
		"mandatories": brand(project).get("mandatories") or "",
		"creative_direction": project.video_idea or "",
		"camera_reference_notes": [note[:400] for note in camera_grammar.get("notes", [])[:4]],
		"unresolved_feedback": [
			{
				**r,
				"scope": r.get("scope", "Historical"),
				"text": r["text"] if len(r["text"]) <= 400 else r["text"][:250] + " … " + r["text"][-150:],
			}
			for r in review_notes
			if r.get("scope") == "Current"
		],
	}
	roster = [
		{
			"key": item["key"],
			"role": item["role"],
			"label": item["label"],
			"keep_rule": item.get("keep_rule", "")[:400],
			"view_count": len(item["views"]),
			"views": [
				{"key": v.get("key", item["key"]), "description": v["description"][:200]}
				for v in item["views"]
			],
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
		"Open with a visible causal event already happening. Invent a coherent situation, prompt reaction, product acquisition/use and visible result. A reaction must not occupy an entire scene on its own. "
		"Supply every prerequisite action before its consequence: acquire, grip, move into contact, perform the use, reveal the changed state. Reaching for a container is not obtaining its contents: show removal before using the item. "
		"Split distinct interactions into motivated shots; preserve object states, supports, screen direction and anatomy across cuts. Repeat the same full place description for one location, not vague same-room placeholders. "
		"Respect the observed product construction: do not invent rigid lids or closure actions for flexible wrapping. Used consumable material stays separate from unused stock; do not restore used material to its clean container as an unexplained reset. "
		"Each shot has ONE coherent interaction and its immediate consequence. Travel, acquisition, extraction and use are different interactions: give them separate shots rather than compressing all into an opening. "
		"For supplied Environment references use the exact reference key as place; the reference description controls that location. "
		"Each non-final scene must advance a concrete subject action, not waiting, approaching alone, posing or camera motion. "
		"Perform gestures promptly in real time. Each non-final shot needs at least two sequential visible actions within one coherent interaction; never a whole shot of noticing/looking. Only the advertised product or its material performs its function, never the actor body or an unrelated prop. "
		"Propose positive relative scene durations and explicit chronological timed Action phases starting at zero, with no gaps. The application allocates exact frames to the requested total and rescales your phase timings. "
		"Provide enough distinct scenes to fit the workflow's declared max_scene_frames at the given fps. Longer total videos need more motivated shots, not an over-capacity ending. "
		"Use bracketed start-end seconds for each phase. Choose timing from the actual action; do not reuse one equal-duration timing pattern throughout the film. "
		"Allocate most runtime to distinct visible product interactions. Result inspection and final presentation must not become repeated long looking/nodding/holding scenes; combine a brief reaction with a tangible action and use one concise ending. "
		"Only supplied actors may appear in prose AND cast: no humans when only a mascot is supplied. Choose the best supplied view key for each scene in cast/products, one view per identity. Gallery views are alternatives of one identity, never additional cast. "
		"Reference observations supply action rhythms, never additional actors, products, claims or sounds. "
		"Avoid applicable problems in unresolved feedback; historical scene numbers are not instructions to reuse an old story, and script writing never resolves feedback. Only state supplied approved claims. Ordinary props and a coherent location may be invented, but name them before use. "
		"Vary adjacent shot sizes with purpose; preserve the action axis; show the product close at use and clearly at the end. "
		"Classify each narrative_stage by its dominant job, not all establish. Use short purposeful beats, "
		"allocate time to visible actions, and end promptly after the final branded composition reads. "
		"Camera behavior is derived later from semantic stage/framing: do not put camera moves in Action. "
		"Use layered depth, shaped directional lighting, material texture and a deliberate palette. "
		"Music must name instrumentation, mood, tempo and cue changes aligned with story beats, ending with a resolved cadence. Sounds must link to visible actions. "
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

	error, latest_script = "", None
	for _attempt in range(3):
		request_prompt = prompt + error
		if latest_script is not None:
			# Edit the complete latest screenplay, rather than asking the creative
			# writer to invent another story from a detached list of action quotes.
			request_prompt = (
				"Edit the supplied complete screenplay to fix the quoted defects. Keep its premise, "
				"identities, format and duration; change only defective actions and their dependent "
				"opening/continuity/result text. Preserve chronological prerequisites across scenes. "
				"A later result must not be inserted into an earlier scene before acquisition/contact. "
				"Mechanical staging notes belong in continuity_rules. Return the complete schema.\n"
				+ "REFERENCE ROSTER: "
				+ json.dumps(roster, ensure_ascii=False)
				+ "\nCONSTRAINTS: "
				+ json.dumps(
					{k: v for k, v in constraints.items() if k != "unresolved_feedback"}, ensure_ascii=False
				)
				+ "\nLATEST SCREENPLAY: "
				+ json.dumps(
					{k: v for k, v in latest_script.items() if k != "timing_compilation"}, ensure_ascii=False
				)
				+ "\nDEFECTS TO REPAIR: "
				+ error
			)
		result = _ask_planner(
			request_prompt,
			system="You write complete multi-scene commercial scripts from visual product references. Return only the requested JSON, using exact enum values and reference keys. The primary user direction takes precedence over motion observations, which are examples rather than a required story.\nPRIMARY USER DIRECTION: "
			+ constraints["creative_direction"]
			+ "\nINVARIANTS FOR ORIGINAL WRITING AND EVERY REPAIR: "
			+ CREATIVE_INVARIANTS,
			sampling_profile="creative_script_repair" if latest_script is not None else "creative_script",
			capability="writer",
			response_schema=script_schema(inventory, constraints),
		)
		try:
			script = fit_generated_timing(
				result, constraints["duration_seconds"], fps, max_scene_frames=constraints["max_scene_frames"]
			)
			script = validate_script(script, inventory, constraints)
			latest_script = script
			findings = review_script_actions(
				script,
				roster,
				constraints["unresolved_feedback"],
				{
					k: constraints[k]
					for k in (
						"approved_claims",
						"avoid",
						"mandatories",
						"camera_reference_notes",
						"creative_direction",
					)
				},
			)
			blocking = [row for row in findings["issues"] if row["category"] != "production_detail"]
			if blocking:
				error = (
					"\nRevise the complete script to fix these grounded issues in the LATEST draft: "
					+ json.dumps(findings["issues"], ensure_ascii=False)
					+ "\nREJECTED ACTION CHAIN: "
					+ json.dumps(
						[{k: scene[k] for k in ("duration_seconds", "action")} for scene in script["scenes"]],
						ensure_ascii=False,
					)
				)
				continue
			for row in findings["issues"]:
				if row.get("text_cross_check"):
					# A retracted omission is already covered by the action sequence;
					# repeating its requested action would introduce duplicate use.
					continue
				scene = script["scenes"][row["scene"] - 1]
				scene["continuity_rules"] += "\nProduction direction: " + row["instruction"]
			script = validate_script(script, inventory, constraints)
			script["action_review"] = findings
			return script

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
	reference_options = reference_choices(inventory)
	roles = {key: value["role"] for key, value in reference_options.items()}
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
		scene["action"] = normalize_action_separators(scene["action"])
		if read_timed_actions(scene["action"], duration) is None:
			raise ValueError("Use explicit chronological timed action phases, not camera-only prose.")
		for key, choices in (("shot_framing", FRAMINGS), ("shot_angle", ANGLES), ("narrative_stage", STAGES)):
			if scene.get(key) not in choices:
				raise ValueError("Unsupported " + key + ".")
		if "subject_motion" in scene and scene["subject_motion"] not in MOTIONS:
			raise ValueError("Unsupported subject_motion.")
		for field, allowed in (("cast", {"Character", "Person"}), ("products", {"Product"})):
			keys = scene.get(field)
			if (
				not isinstance(keys, list)
				or any(not isinstance(k, str) for k in keys)
				or len(keys) != len(set(keys))
				or any(roles.get(k) not in allowed for k in keys)
			):
				raise ValueError("Scene " + field + " must use supplied identities only.")
			if len({reference_options[k]["identity"] for k in keys}) != len(keys):
				raise ValueError(
					"Use one view per identity in each scene; alternate photos are not extra cast."
				)
		for field in ("voice_over", "audio_cues", "on_screen_text"):
			if not isinstance(scene.get(field, ""), str):
				raise ValueError("Scene audio and text must be strings.")
	if not 1 <= total <= 60 or abs(total - declared_duration) > 0.001:
		raise ValueError(
			f"Scene durations sum to {total:g}s, but declared total is {declared_duration:g}s. Redistribute {declared_duration - total:g}s across purposeful action scenes so the sum is exact, not a prolonged closing hold."
		)
	if constraints.get("duration_seconds") and abs(total - float(constraints["duration_seconds"])) > max(
		0.001, 0.5 / constraints.get("fps", 1000)
	):
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

	from joymedia.services.intake.references import brand, preservation_modes
	from joymedia.services.intake.template import BRIEF_ROWS, HEADER_ROW, SHEET_TITLES, build_template
	from joymedia.services.planning.workbook import BRAND_FIELDS, REFERENCE_COLUMNS, SCENE_COLUMNS
	from joymedia.services.scene.references import canonical_reference_rows

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
			r.reference_key
			for r in canonical_reference_rows(project.selected_media)
			if r.reference_role in {"Character", "Person"}
		)
		or "none",
	}
	for key, row in BRIEF_ROWS:
		sheet.cell(row, 2, metadata[key])
	cursor = 0.0

	def clock(seconds):
		return f"{int(seconds // 60)}:{seconds % 60:012.9f}"

	for i, scene in enumerate(script["scenes"], HEADER_ROW + 1):
		end = cursor + float(scene["duration_seconds"])
		values = {
			**scene,
			# Automatic screenplay labels are proposals, not authored overrides.
			# The normal production planner owns semantic stage classification and
			# the shared camera compiler consumes its validated shot structure.
			"narrative_stage": "",
			"timing": f"{clock(cursor)} - {clock(end)}",
			"continuity": scene["continuity_rules"] + "\nRequired visible change: " + scene["visible_change"],
			"cast": ", ".join(scene["cast"]) or "none",
			"products": ", ".join(scene["products"]) or "none",
		}
		for column, key in enumerate(SCENE_COLUMNS, 1):
			sheet.cell(i, column, values.get(key, ""))
		cursor = end
	last = sheet.cell(HEADER_ROW, len(SCENE_COLUMNS)).column_letter
	sheet.tables["Storyboard"].ref = f"A{HEADER_ROW}:{last}{HEADER_ROW + len(script['scenes'])}"
	refs = book[SHEET_TITLES["references"]["en"]]
	modes = preservation_modes(project)
	for row in refs.iter_rows(min_row=2):
		for cell in row:
			cell.value = None
	for i, row in enumerate(project.selected_media, 2):
		if row.reference_role not in {"Product", "Character", "Person", "Logo", "Environment"}:
			continue
		asset = frappe.get_doc("Asset Version", row.asset_version)
		analysis = frappe.parse_json(asset.analysis_json or "{}") or {}
		values = {
			"name": row.reference_key,
			"type": "Real person" if row.reference_role == "Person" else row.reference_role,
			"file": frappe.get_doc("File", {"file_url": asset.file}).file_name,
			"keep_rule": row.keep_rule or "",
			"preservation_mode": modes.get(row.asset_version, ""),
			"description": analysis.get("description", "") if row.reference_role == "Environment" else "",
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
