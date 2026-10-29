"""Production planning: turn creative beats into production shots.

An imported storyboard describes what the advertiser wants to *see* (creative beats). The
generation models need something different: a concrete starting frame for the image model
and a motion description for the video model, plus the references each frame depends on.
This stage derives those from each beat with the planner model. The advertiser's own words
(timing, voice-over, on-screen text, claims, the source rows) are never rewritten; only
prompts, continuity and reference assignments are proposed, for the user to review.
"""

import json
import re

import frappe
import requests
from frappe import _

from joymedia.services.planning.language_rules import (
	CAMERA_LABEL,
	CAMERA_TERMS,
	COLOUR_TERMS,
	COMMON_CAPITALISED,
	FRAMING_WORDS,
	MIN_SENTENCE_COVERAGE,
	STOPWORDS,
	_foreign_share,
	_name_phrase,
	_words,
	added_share,
	beat_coverage,
	brand_words,
	camera_direction,
	camera_glossary,
	colour_terms,
	english_part,
	invented_names,
	is_english,
	keeps_every_sentence,
	looks_english,
	split_views,
	with_glossary,
)
from joymedia.services.planning.llm import _normalized_motion_plan
from joymedia.services.runtime.sampling import sampling

MAX_PROMPT_CHARS = 700
MAX_IMAGE_WORDS = 70
SYSTEM_PROMPT = (
	"You are a production planner for AI-generated video advertisements. You convert one creative beat "
	"into one production shot for an image model (the starting frame) and an image-to-video model (the "
	"motion). Return JSON only."
)


class PlannerUnavailableError(RuntimeError):
	"""The configured text service is temporarily unreachable, not a bad script."""


def plan_production_shot(project, shot, *, previous_end_state="", references=None, previous_setting=""):
	"""Ask the planner for one shot's production plan and return it validated (nothing is saved)."""
	references = references if references is not None else project_reference_options(project)
	beat = creative_beat(project, shot)
	if beat.get("cast_declared") and not beat.get("cast") and beat.get("products"):
		from joymedia.services.scene.prompt_scope import assert_product_only_direction

		assert_product_only_direction("\n".join(str(beat.get(k) or "") for k in ("action", "rules")))
	if project.get("planning_mode") == "Follow the sheet":
		from joymedia.services.scene.references import identity_key, named_reference_views

		view_keys = named_reference_views(
			project.get("selected_media") or [], [*(beat.get("cast") or []), *(beat.get("products") or [])]
		)
		rows = {row.reference_key: row for row in project.get("selected_media") or []}
		references = [dict(reference) for reference in references]
		for reference in references:
			canonical = rows.get(reference["key"])
			views = [
				rows[key]
				for key in view_keys
				if key in rows and canonical and identity_key(rows[key]) == identity_key(canonical)
			]
			if views:
				descriptions = []
				for view in views:
					analysis = (
						frappe.parse_json(
							frappe.db.get_value("Asset Version", view.asset_version, "analysis_json") or "{}"
						)
						or {}
					)
					from joymedia.services.scene.prompt_scope import reference_description

					appearance = reference_description(analysis, str(view.reference_role or "").lower())
					if appearance:
						pose = analysis.get("qualified_pose_and_support")
						descriptions.append(
							appearance
							+ (
								" Reference body state: "
								+ str(pose)
								+ ". Empty paws describe this reusable reference only; authored scene props and contact remain required."
								if pose
								else ""
							)
						)
				if descriptions:
					reference["description"] = "Chosen source view: " + " | ".join(descriptions)
		plan = follow_the_sheet(project, shot, beat, references, previous_setting, previous_end_state)
		plan["reference_views"] = view_keys
		# Sheet-authored productions use the same source-art guarantee as AI
		# Director productions.  The prose can name a visible pack even when the
		# sheet's cast/products columns did not tag it as a product beat.
		plan["reference_keys"], visible_product_notes = ground_visible_product_keys(
			project, plan, plan.get("reference_keys") or [], references, beat=beat
		)
		plan.setdefault("notes", []).extend(visible_product_notes)
		from joymedia.services.planning.product_views import (
			constrain_product_views,
			requested_product_view_for_scene,
		)

		return constrain_product_views(
			project,
			plan,
			required_view=requested_product_view_for_scene(
				{"visual_camera": beat["camera"], "product_view": beat.get("product_view")}
			),
		)
	prompt = build_planning_prompt(project, shot, beat, references, previous_end_state)
	raw = _ask_planner(prompt)
	if len(str((raw or {}).get("image_prompt") or "").split()) > MAX_IMAGE_WORDS:
		# One corrective retry: the image prompt must describe a single frame, not the whole action.
		raw = _ask_planner(
			prompt
			+ f"\nYour previous image_prompt was too long. Rewrite it as one still frame of at most {MAX_IMAGE_WORDS - 10} words."
		)
	_discard_inferred_camera(project, raw)
	plan = normalize_production_shot(
		raw,
		reference_keys={reference["key"] for reference in references},
		duration=float(shot.duration_seconds or 0),
		is_first=int(shot.shot_number or 0) <= 1,
	)
	if not looks_english(plan["video_prompt"]):
		# A video prompt that copied the beat's language, or mixed it with a translation, is not usable: the
		# movement of the beat's English translation replaces it.
		plan["video_prompt"] = motion_only(project, beat["summary"], references) or beat["summary"]
		plan["motion_plan"] = {
			"actions": [
				{"start": 0, "end": float(shot.duration_seconds or 1), "action": plan["video_prompt"]}
			]
		}
		plan["notes"].append(
			"The planner did not answer in English, so the video prompt is the beat's movements."
		)
	for key in ("image_prompt", "setting_prompt", "sound_effects"):
		# The models read English; a planner answer that copied the beat's own language is translated.
		plan[key] = translate(plan.get(key), project)
	plan["audio"] = audio_direction(project, beat, plan.get("sound_effects"))
	plan["reference_keys"], added_notes = ground_reference_keys(
		project, beat, plan["reference_keys"], references
	)
	plan["reference_keys"], visible_product_notes = ground_visible_product_keys(
		project, plan, plan["reference_keys"], references, beat=beat
	)
	plan["notes"].extend([*added_notes, *visible_product_notes])
	from joymedia.services.planning.product_views import (
		constrain_product_views,
		requested_product_view_for_scene,
	)

	plan = constrain_product_views(
		project,
		plan,
		required_view=requested_product_view_for_scene(
			{"visual_camera": beat["camera"], "product_view": beat.get("product_view")}
		),
	)
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
		plan["motion_plan"] = {
			"actions": [{"start": 0, "end": float(shot.duration_seconds or 1), "action": movement}]
		}
		plan["notes"].append(
			"Plan covers too little of the beat, so the beat's own wording, reduced to its movements, is used as the video prompt."
		)
	return _apply_camera_profile(project, shot, plan)


def motion_only(project, text, references, inventory="", attempt=0):
	from joymedia.services.planning.director_rules import CINEMATOGRAPHY_RULES
	from joymedia.services.project.formats import ratio_label
	from joymedia.services.scene.contract import STAGING_RULES

	"""The beat's actions and camera moves only, in English, using only what the first frame contains.

	`inventory` names what the first frame shows. Anything else the beat mentions (other boxes, people, products)
	is dropped, and what such an entity does is done by a listed character instead, because a video model draws
	every extra entity the text names.
	"""
	cast = ", ".join(r["label"] for r in references or [] if r.get("role") in ("Character", "Person"))
	prompt = (
		"Rewrite this storyboard beat as ONLY what moves: the actions of the characters and the camera, in time "
		"order, in at most 60 words of English. Remove every description of the place, lighting, time of day, "
		"colours and objects that are not moving, every position in the frame, and every quantity, name or word that "
		"would print as text on an object. "
		+ (
			f"The characters and products in the scene are exactly: {inventory}. Do not add any other person, character "
			"or product. Keep every other object the beat names (cups, drinks, food, napkins…) as that object: never turn "
			"an object into the advertised product, which appears only where the beat itself names it. "
			if inventory
			else f"Characters: {cast or 'as in the beat'}; every named family role is one of them. "
		)
		+ "Do not add anything the beat does not say. "
		+ STAGING_RULES
		+ " Keep this rewrite faithful; report only motion in the requested JSON field. "
		+ f'\nBEAT: {text}\nReturn {{"motion": "..."}}'
		+ (f"\n(Answer again, attempt {attempt + 1}: English only, faithful to the beat.)" if attempt else "")
	)
	raw = _ask_planner(
		prompt,
		system="You rewrite storyboard beats faithfully. Return JSON only.",
		sampling_profile="faithful_rewrite",
		capability="translator",
	)
	return " ".join(str((raw or {}).get("motion") or "").split())


PLACE_WORDS = re.compile(
	r"\b(kitchen|dining|room|home|house|garden|park|picnic|office|bathroom|bedroom|living|outdoor|outdoors|street|beach|shop|"
	r"store|studio|restaurant|cafe|school|hospital|hotel)\b",
	re.I,
)
PRODUCT_WORDS = re.compile(
	r"\b(pack|packs|package|packages|bag|bags|bottle|bottles|box|boxes|product|products)\b", re.I
)
MANY_PRODUCTS = re.compile(r"\b(products|all (?:the )?products|range|lineup|collection)\b|các sản phẩm", re.I)


# A rewrite must keep this share of the beat's own content words, and add at most this share of new ones, or the
# faithful translation is used as it is.
MIN_REWRITE_COVERAGE = 0.8
MAX_REWRITE_ADDITIONS = 0.35


def faithful_rewrite(project, source, references, inventory=""):
	"""The beat's movement rewritten for the video model, or the beat's own English when the rewrite is not faithful.

	A rewrite is kept only when it keeps the beat's content and adds next to nothing: it is for trimming, never for
	inventing. Two attempts; then the translation itself is used.
	"""
	for attempt in range(2):
		movement = motion_only(project, source, references, inventory, attempt=attempt)
		if (
			movement
			and is_english(movement)
			and beat_coverage(source, movement)[0] >= MIN_REWRITE_COVERAGE
			and keeps_every_sentence(source, movement)
			and added_share(source, movement, inventory) <= MAX_REWRITE_ADDITIONS
			and len(movement) <= 1.6 * len(source) + 60
		):
			return movement
	return source if is_english(source) else "The characters act out the scene."


def follow_the_sheet(project, shot, beat, references, previous_setting="", previous_end_state=""):
	"""A production plan taken from the storyboard's own text.

	Free prose uses faithful translation. Explicit timed phases retain their authored
	intervals while the production planner derives an opening still and shot grammar.

	The advertiser wrote the scene; nothing is invented. Characters are the ones the beat names (by the exact name
	the sheet uses for them), one product pack appears when the beat is about the product (all of them when it says
	"products"), the logo bookends the film, the sounds are the sheet's own cues, and the movement is the beat's
	action rewritten in English against exactly what the first frame contains.
	"""
	from joymedia.services.intake.references import find_reference, place_row, props_in
	from joymedia.services.planning.camera import camera_planning_rules
	from joymedia.services.planning.roles import family_role, names_family
	from joymedia.services.planning.timed_actions import read_timed_actions

	# Read the original cell before translation or motion summarization can flatten
	# its line breaks and explicit pace. Untimed workbooks retain their old path.
	timed = read_timed_actions(
		beat.get("action_source") or beat.get("action"), float(shot.duration_seconds or 0)
	)

	raw = beat.get("raw", "")
	text = " ".join((raw, beat.get("summary", "")))
	keys, notes, extra_rules = [], [], []
	named = (
		beat.get("cast") or beat.get("products") or beat.get("cast_declared") or beat.get("products_declared")
	)
	# A character is in the scene when the beat names it ("Gấu mẹ"); a word for the whole family ("gia đình", "cả nhà",
	# "family") brings in every character named as a family member (bố, mẹ, con, ông, bà…). A lone role word is not
	# enough: "sợ mẹ mắng" (afraid mum will scold) names a mother who is not in the picture.
	group = names_family(text)
	if named:
		# The sheet says who and what is in the scene by name: exactly those, nothing inferred.
		for kind, names in (("cast", beat.get("cast") or []), ("products", beat.get("products") or [])):
			roles = ("Character", "Person") if kind == "cast" else ("Product",)
			for name in names:
				reference = find_reference(name, [r for r in references if r["role"] in roles])
				if reference:
					keys.append(reference["key"])
				else:
					notes.append(
						f"Needs a picture: the sheet names '{name}' in this scene but the project has no picture of it; it is drawn from the text."
					)
	else:
		for reference in references:
			if reference["role"] != "Character":
				continue
			if _name_phrase(reference["label"]).casefold() in text.casefold() or (
				group and family_role(reference["label"])
			):
				keys.append(reference["key"])
		products = [r for r in references if r["role"] == "Product"]
		if products and shows_product(project, text):
			keys.extend(r["key"] for r in (products if MANY_PRODUCTS.search(text) else products[:1]))
	setting = ""
	if beat.get("place"):
		# A named place: its own picture, or its description, the same words for every scene set there (one room).
		picture = find_reference(beat["place"], [r for r in references if r["role"] == "Environment"])
		if picture:
			keys.append(picture["key"])
		row = place_row(beat["place"], project)
		setting = translate((row or {}).get("description") or beat["place"], project).strip()
		if (row or {}).get("keep_rule"):
			# What must hold wherever the place is used ("one room, one table, one cup for scenes 1–6").
			extra_rules.append(translate(row["keep_rule"], project).strip(" ."))
	# A recurring object the scene names keeps one description, the same in every scene (the sheet's props).
	for name, description in props_in(raw, project):
		extra_rules.append(translate(f"{name}: {description}" if description else name, project).strip(" ."))
	logos = [r for r in references if r["role"] == "Logo"]
	scenes = frappe.db.count("Shot", {"media_project": project.name, "is_removed": 0})
	if logos and int(shot.shot_number or 0) in (1, scenes):
		keys.append(logos[0]["key"])
	if not keys and not named:
		keys = [r["key"] for r in references if r["role"] == "Character"][:1]
	keys = list(dict.fromkeys(keys))
	plan = {
		"image_prompt": " ".join(
			filter(
				None,
				(
					camera_direction(beat.get("camera")),
					english_roles(beat.get("action") or "", references, project.get("product_name")),
				),
			)
		)[:MAX_PROMPT_CHARS]
		or beat["summary"][:MAX_PROMPT_CHARS],
		# A beat that names no place stays where the film already is.
		"setting_prompt": setting or _place(project, beat) or _place(project, beat, 1) or previous_setting,
		"video_prompt": "",
		"reference_keys": keys,
		"continuity_mode": "New Scene",
		"start_state": "",
		"end_state": "",
		"motion_plan": {"actions": []},
		"notes": ["Taken from the sheet; the planner only translated it.", *notes],
		"sound_effects": "",
	}
	by_key = {r["key"]: r for r in references}
	inventory = "; ".join(by_key[k]["label"].split(" (")[0] for k in keys if k in by_key)
	if timed or camera_planning_rules(project):
		authored = timed or [
			{"start": 0, "end": float(shot.duration_seconds), "action": beat.get("action") or beat["summary"]}
		]
		return _timed_sheet_plan(
			project, shot, beat, references, plan, authored, previous_end_state=previous_end_state
		)
	camera = (beat.get("camera") or "") + " " + (beat.get("action") or "")
	split_screen = bool(re.search(r"split[- ]?screen|chia \d? ?màn", camera, re.I))
	# Only the action describes what moves; the camera text is the part the translator garbles most.
	source = beat.get("action") if beat.get("action") and is_english(beat.get("action")) else beat["summary"]
	if not is_english(source):
		source = translate(source, project)
	views = []
	if split_screen:
		# The views are drawn as stacked panels of one first frame (keyframes.overlay.split_screen_keyframe); each is
		# translated on its own, with the whole beat as context, so none is dropped or merged.
		listed = beat.get("action_source") or beat.get("action") or beat["summary"]
		views = [
			{"text": translate(view, project, about=listed).strip(" .;"), "source": view}
			for view in split_views(listed)
		]
	# A split screen's text is its list of views: a rewrite could drop one, so the faithful translation is kept.
	movement = source if views else faithful_rewrite(project, source, references, inventory)
	# The video model prints names it does not understand: the sheet's names become plain English roles.
	movement = english_roles(movement, references, project.get("product_name"))
	# The sheet's own camera direction (framing and movement) goes to the video model as written.
	camera = "" if split_screen else camera_direction(beat.get("camera"))
	if views:
		# The translated list is replaced by the numbered views; what the beat says before its list is kept.
		movement = re.split(r"\s*(?:^|\s)1[.)]\s", movement, maxsplit=1)[0].strip(" :;,.")
		movement = (
			f"Split screen of {len(views)} stacked panels, top to bottom: "
			+ "; ".join(f"{number}. {view['text']}" for number, view in enumerate(views, 1))
			+ (f". {movement}." if movement else ".")
		)
	plan["video_prompt"] = movement + (f" Camera: {camera}" if camera else "")
	rules = "; ".join(filter(None, [str(beat.get("rules") or "").strip(" ."), *extra_rules]))
	if rules:
		# The sheet's Logic / Continuity column, the place's rule and the props: their own paragraph (prompts.scene_rules).
		plan["video_prompt"] += f"\n\nRules: {rules}."
	plan["views"] = views
	plan["motion_plan"] = {
		"actions": [{"start": 0, "end": float(shot.duration_seconds or 1), "action": movement}]
	}
	plan["audio"] = audio_direction(project, beat)
	if split_screen:
		if not views:
			plan["notes"].append(
				"Needs editing: the sheet asks for a split screen but lists no numbered views."
			)
		plan["setting_prompt"] = (
			setting or previous_setting
		)  # the views have their own places; the film's place stays
	plan["coverage"], plan["held_back"] = 1.0, False
	return plan


def _discard_inferred_camera(project, raw):
	"""Policy owns inferred camera intent; explicit authored plans use their normal validator."""
	from joymedia.services.planning.camera import camera_planning_rules

	if camera_planning_rules(project) and isinstance(raw.get("motion_plan"), dict):
		raw["motion_plan"].pop("camera_intent", None)


def _apply_camera_profile(project, shot, plan):
	from joymedia.services.planning.camera import (
		camera_planning_rules,
		executable_inferred_intent,
		infer_cinematic_intent,
		reference_camera_grammar,
	)

	move = _authored_camera_move(project, shot)
	if move:
		# An authored move (sheet column or AI script) is the director's choice;
		# the compiler still applies its framing and product-legibility safeguards.
		from joymedia.services.planning.shot_structure import CAMERA_MOVES, MOVE_BEHAVIOR

		if move not in CAMERA_MOVES:
			raise ValueError("Unsupported authored camera move: " + move)
		count = frappe.db.count("Shot", {"media_project": project.name, "is_removed": 0})
		number = int(shot.shot_number or 0)
		plan.setdefault("motion_plan", {})["camera_intent"] = {
			"behavior": MOVE_BEHAVIOR[move],
			"allow_reframe": move != "static",
			"purpose": "hook" if number == 1 else "resolve" if number == count else "reveal",
			"energy": "brisk" if number == 1 else "measured",
			"source": "authored",
		}
		return plan
	if camera_planning_rules(project):
		structure = plan.get("motion_plan", {}).get("shot_structure")
		if not structure:
			raise ValueError(
				"The cinematic camera profile requires a structured shot plan. Replan this scene."
			)
		count = frappe.db.count("Shot", {"media_project": project.name, "is_removed": 0})
		if (
			count > 1
			and int(shot.shot_number or 0) == count
			and structure.get("stage") not in {"present", "hero"}
		):
			# A final product view is a resolution, even when the planner labels
			# its close observation as inspection. Use the hero camera grammar.
			# A one-scene film keeps its opening plan: it has no separate ending.
			structure["stage"] = "hero"
		# The production planner infers stage from prose, but an unsupported
		# precision label would wrongly lock a wide opening. Extraction needs an
		# actual removal action; placement alone is a presentation/establish beat.
		if structure.get("stage") == "extract":
			import re

			action_text = " ".join(
				str(row.get("action") or "") for row in plan.get("motion_plan", {}).get("actions") or []
			)
			if not re.search(r"\b(?:extract|pull|withdraw|remove|take\s+out)\w*\b", action_text, re.I):
				structure["stage"] = (
					"establish"
					if int(shot.shot_number or 0) == 1 and structure.get("framing") in {"wide", "full"}
					else "present"
				)
				plan.setdefault("notes", []).append(
					"Camera stage corrected: no extraction action is present in this shot."
				)
		preferred = infer_cinematic_intent(
			structure,
			opening=int(shot.shot_number or 0) == 1,
			closing=int(shot.shot_number or 0) == count,
			grammar=reference_camera_grammar(project),
		)
		resolved = executable_inferred_intent(
			preferred,
			structure,
			{
				str(r.get("reference_role") or r.get("input_role") or "").lower()
				for r in shot.get("generation_inputs") or shot.get("references") or []
			},
			generated_composition=bool(
				project.get("workflow") and "reference_only" in _workflow_controls(project.workflow)
			),
		)
		plan["motion_plan"]["camera_intent"] = resolved
		if resolved != preferred:
			plan.setdefault("notes", []).append(
				f"Reference preference {preferred['behavior']} resolved to {resolved['behavior']} using available boundaries; framing safeguards still apply."
			)
	return plan


def _authored_camera_move(project, shot):
	"""The sheet's "Camera move" for this scene, read directly (it needs no translation)."""
	try:
		source = frappe.parse_json(project.storyboard_source_json or "{}") or {}
		# A screenplay generated by AI Director is a narrative proposal. Its
		# camera_move cells are not client-authored instructions; the shared camera
		# grammar resolves them after semantic shot structure is known.
		if source.get("generation_origin") == "ai_director":
			return ""
		scenes = source.get("selected_demo", {}).get("scenes", [])
	except (TypeError, ValueError):
		return ""
	name = shot.get("storyboard_beat") or shot.get("shot_name")
	return next((str(s.get("camera_move") or "").strip() for s in scenes if s.get("beat_name") == name), "")


def _workflow_controls(workflow_name):
	from joymedia.services.workflows.capabilities import controls

	return controls(frappe.get_doc("Generation Workflow", workflow_name))


def _timed_sheet_plan(project, shot, beat, references, base, authored, *, previous_end_state=""):
	"""Use the normal production planner for staging; preserve the sheet's intervals.

	The shared shot grammar chooses camera behavior downstream. No provider,
	product, scene count or native frame grid belongs in workbook interpretation.
	"""
	actions = [
		dict(
			row,
			action=english_roles(translate(row["action"], project), references, project.get("product_name")),
		)
		for row in authored
	]
	from joymedia.services.planning.camera import camera_planning_rules
	from joymedia.services.planning.director_rules import CINEMATOGRAPHY_RULES
	from joymedia.services.planning.shot_structure import PLANNING_RULES as STRUCTURE_RULES
	from joymedia.services.project.formats import ratio_label
	from joymedia.services.scene.contract import STAGING_RULES, TRANSITION_RULES

	camera_rules = camera_planning_rules(project)
	# Serialize authored event timing instead of asking the model to predict it again.
	labels = {
		"Person": "the referenced person",
		"Character": "the referenced character",
		"Product": "the advertised product",
		"Environment": "the referenced setting",
		"General": "the referenced prop",
		"Logo": "the referenced brand artwork",
	}
	entities = [
		{"id": f"ref{i + 1}", "label": labels[r["role"]]}
		for i, r in enumerate(references)
		if r["key"] in base["reference_keys"]
	]
	contract = {
		"version": 1,
		"entities": entities,
		"relations": [],
		"checks": [],
		"events": [
			{
				"id": f"action{i + 1}",
				"description": row["action"],
				"start": row["start"],
				"end": row["end"],
				"after": [f"action{i}"] if i else [],
			}
			for i, row in enumerate(actions)
		],
	}
	prompt = (
		"Convert this authored timed scene into an English production plan, JSON only. "
		"Preserve every subject and action; invent no objects, actors, packaging layers or claims. "
		"image_prompt: ONE opening still before the first timed action, at most 60 words. "
		"A reusable character reference does not replace the authored opening's held objects or contact. "
		"Do not copy its empty-paw or relaxed-arm conditions into an opening already holding, folding or placing material. "
		"Carry the acquired material from the preceding state until its authored placement or release. "
		+ (
			_locked_product_opening_rule()
			if any(r["role"] == "Product" and r["key"] in base["reference_keys"] for r in references)
			else "No advertised package belongs in this opening. Keep authored loose materials and working props visible. "
		)
		+ "setting_prompt: place and lighting only, at most 30 words. video_prompt: authored motion only. "
		"start_state and end_state: concise visible states including the actor's posture, support and held objects. "
		"Carry unchanged posture, support and object placement from the preceding state; focusing on a new action must not silently move an actor onto furniture or move an object to a different support. Use New Scene for a direct cut. "
		"needs_editing: report impossible action timing without omitting actions. "
		"Infer motion_plan.shot_structure and physical scene constraints; "
		"do NOT generate camera_intent, entities, events or actions: the application serializes authored events and timing. "
		"You may declare additional_entities:[{id:prop_id,source_quote:exact words from VISUAL/ACTIONS/CONTINUITY/PLACE,kind:prop|support|material|body_part}]. "
		"Only explicitly authored props, supports, materials and body parts may be added; never another actor or product. "
		"Optional relations/checks/proportions/counts/parts/properties must reference given or grounded entity IDs. "
		"For state-changing authored interactions, supply visible before/during/after/forbidden transition observations, "
		"using the given EVENT IDs. Preserve actions and infer only their observable physical consequences. "
		"keep_visible must use the given ENTITY IDs. "
		"Use one main camera behavior from shared shot grammar. Camera movement never substitutes for subject action. "
		+ STRUCTURE_RULES
		+ CINEMATOGRAPHY_RULES
		+ "\nFORMAT: "
		+ (ratio_label(project.delivery_width, project.delivery_height) or "unspecified")
		+ "\n"
		+ previous_coverage(project, shot)
		+ STAGING_RULES
		+ TRANSITION_RULES
		+ camera_rules
		+ "\nENTITY IDs: "
		+ json.dumps(entities)
		+ "\nAUTHORITATIVE ACTIONS: "
		+ json.dumps(actions, ensure_ascii=False)
		+ "\nEVENT IDs: "
		+ json.dumps(contract["events"], ensure_ascii=False)
		+ "\nVISUAL: "
		+ str(beat.get("camera") or "")
		+ "\nCONTINUITY: "
		+ str(beat.get("rules") or "")
		+ "\nPLACE: "
		+ base["setting_prompt"]
		+ "\nPREVIOUS INTENDED END STATE: "
		+ previous_end_state
		+ "\nPreserve unchanged prop states across coverage of the same location; do not reset them without an authored action. The current authored action/location takes precedence; do not transfer fixed room props to a new place."
		+ "\nREFERENCES: "
		+ json.dumps(
			[
				{k: r.get(k) for k in ("key", "label", "role", "description")}
				for r in references
				if r["key"] in base["reference_keys"]
			],
			ensure_ascii=False,
		)
		+ '\nReturn {"image_prompt":"","setting_prompt":"","video_prompt":"","reference_keys":[],"continuity_mode":"New Scene","start_state":"","end_state":"","motion_plan":{"shot_structure":{"stage":"","framing":"","angle":"","subject_motion":"","keep_visible":[]},"scene_contract":{"transitions":[]}},"needs_editing":""}. Include every shot_structure key. Camera intent is derived by application policy.'
	)
	from joymedia.services.planning.shot_structure import authored_coverage

	coverage = authored_coverage(beat)
	source_prompt = prompt
	# A bounded schema-repair retry fixes malformed inferred structure, never the
	# authored actions. Invalid output must not silently lose physical constraints.
	for attempt in range(3):
		raw = _ask_planner(prompt, sampling_profile="timed_production_plan")
		inferred = raw.setdefault("motion_plan", {}).get("scene_contract") or {}
		try:
			from joymedia.services.planning.grounding import grounded_contract

			authored_contract = grounded_contract(
				contract,
				inferred,
				"\n".join(
					[
						str(beat.get("camera") or ""),
						str(beat.get("rules") or ""),
						base["setting_prompt"],
						*(row["action"] for row in actions),
					]
				),
			)
			raw["motion_plan"].update(actions=actions, scene_contract=authored_contract)
			# Timed actions are authoritative, including a deliberate static hold.
			# Use them before validation: an inferred empty motion description must
			# not reject a packshot whose authored action is already complete.
			raw["video_prompt"] = " ".join(row["action"] for row in actions)
			if coverage:
				raw["motion_plan"].setdefault("shot_structure", {}).update(coverage)
			# Visibility is advisory camera metadata. The model sometimes names a
			# prop by its label instead of its entity ID; preserve declared targets
			# and let the scene contract, not a stray target, define what exists.
			structure = raw["motion_plan"].get("shot_structure") or {}
			if isinstance(structure, dict) and isinstance(structure.get("keep_visible"), list):
				entity_ids = {entity["id"] for entity in authored_contract.get("entities", [])}
				structure["keep_visible"] = [key for key in structure["keep_visible"] if key in entity_ids]
			_discard_inferred_camera(project, raw)
			plan = normalize_production_shot(
				raw,
				reference_keys={r["key"] for r in references},
				duration=float(shot.duration_seconds),
				is_first=int(shot.shot_number or 0) <= 1,
			)
			break
		except (ValueError, frappe.ValidationError) as exc:
			if attempt == 2:
				raise
			# The source prompt already contains all immutable inputs and schemas.
			# Repeating them with the application's expanded contract can exhaust
			# a small planner context before it can repair its own inferred fields.
			proposal = {
				**raw,
				"motion_plan": {
					"shot_structure": raw["motion_plan"].get("shot_structure"),
					"scene_contract": inferred,
				},
			}
			prompt = (
				source_prompt
				+ "\n\n"
				+ "Repair this production-plan JSON without changing its subjects, opening, actions or timing. "
				"Return the complete corrected JSON, no commentary. Schema error: " + str(exc) + ". "
				"Include stage, framing, angle, subject_motion and keep_visible in shot_structure; [] is allowed for keep_visible. "
				"Every keep_visible entry must equal a declared entity id, never its label. "
				"Transition event must use an authored EVENT ID. Do not regenerate events or actions. "
				"image_prompt is one opening still of at most 60 words. "
				+ "\nINVALID PLAN: "
				+ json.dumps(proposal, ensure_ascii=False)
			)
	if not plan["motion_plan"].get("shot_structure"):
		frappe.throw(_("Timed scene planning did not provide shot structure. Please replan the scene."))
	plan["motion_plan"]["actions"] = actions
	plan["motion_plan"]["shot_structure"].update(coverage)
	_apply_camera_profile(project, shot, plan)
	plan["video_prompt"] = " ".join(row["action"] for row in actions)
	if beat.get("products") and not beat.get("cast"):
		# For a product-only insert the authored action owns both boundaries.
		# An inferred carry-over from the previous character scene would add an
		# unreferenced actor to the H3 prompt despite a product-only contract.
		plan["start_state"] = actions[0]["action"][:300]
		plan["end_state"] = actions[-1]["action"][:300]
	if beat.get("rules"):
		plan["video_prompt"] += "\n\nRules: " + beat["rules"]
	plan["reference_keys"] = base["reference_keys"]
	plan["setting_prompt"] = base["setting_prompt"] or plan["setting_prompt"]
	plan["notes"] = [
		*base["notes"][1:],
		*plan["notes"],
		"Action timing and ordered events preserved from the workbook; opening staging uses the shared production planner.",
	]
	plan["audio"] = audio_direction(project, beat)
	plan["views"], plan["coverage"] = [], 1.0
	plan["held_back"] = any(note.startswith("Needs editing:") for note in plan["notes"])
	return plan


def english_roles(text, references, product_name=""):
	"""The text with each character's name as the sheet writes it ("Gấu con") replaced by its English role, and the
	product's own name by "the advertised product": the video model prints names it is
	given onto objects."""
	from joymedia.services.planning.prompts import _display_name, cast_number

	characters = [r for r in references if r.get("role") in ("Character", "Person")]
	labels = [r["label"] for r in characters]
	# Replace longer labels before their shorter prefixes.
	for reference in sorted(characters, key=lambda r: len(_name_phrase(r["label"])), reverse=True):
		name = _name_phrase(reference["label"])
		if name and not name.isascii():
			number, total = cast_number(reference["label"], labels)
			display = _display_name(
				reference["label"], number, total, person=reference.get("role") == "Person"
			)
			text = re.sub(re.escape(name), display, text, flags=re.I)
	products = {_name_phrase(r["label"]) for r in references if r.get("role") == "Product"} | {
		str(product_name or "").strip()
	}
	for name in sorted((n for n in products if n and not n.isascii()), key=len, reverse=True):
		text = re.sub(
			rf"(?:\b(?:the|a|an)\s+)?{re.escape(name)}(?:\s+(?:package|pack|packet|bag))?",
			"the advertised product",
			text,
			flags=re.I,
		)
	return re.sub(r"(^|[.!?]\s+)the ", lambda m: m.group(1) + "The ", text)


# Camera terms of Vietnamese storyboards, longest first; the small planning model mistranslates these.


PACKAGING_WORDS = re.compile(r"\b(?:bịch|hộp|gói|thùng|chai|lọ|tuýp|sản phẩm)\b", re.I)


def shows_product(project, text):
	"""Whether a beat shows the advertised product: it names the brand or the packaging.

	A generic word for what the product is made of ("giấy", paper) does not count: an ad's problem scene is often
	about an ordinary competitor ("giấy ăn thường lau… bị mủn rách") and must not show the advertised pack failing.
	"""
	words = {w.casefold() for w in re.findall(r"[^\W\d_]+", str(text or ""))}
	return bool(brand_words(project.get("product_name")) & words) or bool(
		PACKAGING_WORDS.search(text) or PRODUCT_WORDS.search(text)
	)


def _place(project, beat, attempt=0):
	"""The place the beat is set in, as a short English phrase; empty when the text names none."""
	text = beat.get("summary", "")
	found = PLACE_WORDS.findall(text)
	if not found:
		return ""
	prompt = (
		"From this storyboard text, write ONLY the place and the light, in one short English sentence, with no "
		f'characters, objects or actions.\nTEXT: {text}\nReturn {{"place": "..."}}'
		+ (f"\n(Attempt {attempt + 1}: name only a real place from the text.)" if attempt else "")
	)
	raw = _ask_planner(
		prompt,
		system="You extract the setting from storyboard text. Return JSON only.",
		sampling_profile="role_translation",
		capability="translator",
	)
	place = " ".join(str((raw or {}).get("place") or "").split())
	# A place has no verbs: an action sentence ("Water stain ... is absorbed") is not one.
	is_action = re.search(
		r"\b(is|are|was|were|being|absorb\w*|plac\w*|pull\w*|lift\w*|hold\w*|pour\w*|spill\w*)\b", place, re.I
	)
	return (
		place
		if looks_english(place) and len(place.split()) <= 25 and not is_action and PLACE_WORDS.search(place)
		else ""
	)


def _locked_product_opening_rule():
	"""The opening still the source-pixel product lock can accept, or nothing without the lock."""
	from joymedia.services.consistency.retention import policy

	if not policy():
		return ""
	return (
		"When the advertised product appears in image_prompt, it rests untouched on its support with its "
		"printed face toward the camera; nobody holds it yet. Any handling starts in video_prompt. "
	)


def project_reference_options(project):
	"""Canonical visual identities the planner may assign to a shot.

	Several approved angles of one character are presented as one choice.  The
	shot binder expands that choice to its variants only after planning, so an AI
	director never mistakes angles of one mascot for multiple characters.
	"""
	from joymedia.services.scene.references import canonical_reference_rows, identity_key

	options = []
	all_rows = list(project.selected_media or [])
	for row in canonical_reference_rows(all_rows):
		if not row.reference_key or not row.asset_version:
			continue
		asset = frappe.db.get_value("Asset Version", row.asset_version, "media_asset")
		if not asset or frappe.db.get_value("Media Asset", asset, "media_type") != "Image":
			continue
		variant_count = sum(1 for item in all_rows if identity_key(item) == identity_key(row))
		option = {
			"key": row.reference_key,
			"label": row.label or row.reference_key,
			"role": row.reference_role or "General",
		}
		option["aliases"] = list(
			dict.fromkeys(
				alias
				for item in all_rows
				if identity_key(item) == identity_key(row)
				for alias in (item.label, item.reference_key)
				if alias
			)
		)
		if variant_count > 1:
			option["description"] = f"{variant_count} approved views of this one identity."
		try:
			analysis = frappe.parse_json(
				frappe.db.get_value("Asset Version", row.asset_version, "analysis_json") or "{}"
			)
		except (TypeError, ValueError):
			analysis = {}
		# What the picture actually shows (pose, framing) lets the prompt agree with it.
		# A character with several approved views is drawn from the view bound to each
		# scene, so the canonical upload's pose and held props (a seated mascot hugging
		# a heart) must not be written into every scene's opening frame.
		several_character_views = variant_count > 1 and str(row.reference_role or "").casefold() in {
			"character",
			"person",
		}
		from joymedia.services.scene.prompt_scope import reference_description

		appearance = (
			reference_description(
				{"identity_appearance": analysis.get("identity_appearance")}
				if several_character_views
				else analysis,
				str(row.reference_role or "").casefold(),
			)
			if isinstance(analysis, dict)
			else ""
		)
		if appearance:
			option["description"] = " ".join(filter(None, (option.get("description"), appearance[:400])))
		options.append(option)
	return options


def creative_beat(project, shot):
	"""The advertiser's own description of the beat, verbatim; imported rows when available."""
	source = {}
	try:
		scenes = (
			(frappe.parse_json(project.storyboard_source_json or "{}") or {})
			.get("selected_demo", {})
			.get("scenes", [])
		)
	except (TypeError, ValueError):
		scenes = []
	earlier = ""
	for index, scene in enumerate(scenes):
		if scene.get("beat_name") == (shot.storyboard_beat or shot.shot_name):
			source = scene
			# Every earlier scene, most recent last: "vụn bánh" in scene 5 is the biscuits of scene 1.
			earlier = " ".join(str(previous.get("action") or "") for previous in scenes[:index])[-1500:]
			break
	text = {
		"camera": source.get("visual_camera") or "",
		"product_view": source.get("product_view") or "",
		**{
			k: source.get(k) or ""
			for k in ("shot_framing", "shot_angle", "narrative_stage", "subject_motion", "camera_move")
		},
		"action": source.get("action") or "",
		"voice_over": source.get("voice_over") or shot.voice_over or "",
		"on_screen_text": source.get("on_screen_text") or shot.caption or "",
		"audio": source.get("audio_cues") or shot.audio_cues or "",
		# Who and what is in the scene and where, by the References sheet's names, and what must hold in it.
		"cast": source.get("cast") or [],
		"cast_declared": source.get("cast_declared", False),
		"products": source.get("products") or [],
		"products_declared": source.get("products_declared", False),
		"place": source.get("place") or "",
		"opening_reference": source.get("opening_reference") or "",
		"ending_reference": source.get("ending_reference") or "",
		"rules": translate(source.get("continuity") or "", project),
	}
	if not (text["camera"] or text["action"]):
		text["action"] = shot.generation_prompt or ""
	# The models read English; the advertiser's original wording stays on the shot and in the source.
	text["raw"] = " ".join(filter(None, (text["camera"], text["action"])))
	camera_vi, text["action_source"] = text["camera"], text["action"]
	# A camera column is a list of short directions: translated whole, the model embroiders it ("light radiating around
	# the pack" became "bokeh … window blinds"); one direction at a time it stays faithful.
	text["camera"] = " ".join(
		filter(
			None,
			(
				translate(part, project).strip()
				for part in re.split(r"\n+|(?<=[.!?])\s+", camera_vi)
				if part.strip()
			),
		)
	)
	text["action"] = translate(text["action"], project, earlier=earlier)
	# Camera directions use a fixed vocabulary: a translation missing one of the sheet's camera terms is replaced by them.
	terms = camera_glossary(camera_vi)
	if terms and any(
		term not in text["camera"].casefold().replace("-", " ").replace("slow-motion", "slow motion")
		for term in (atom.replace("-", " ") for atom in re.split(r", | to ", terms))
	):
		text["camera"] = with_glossary(text["camera"], terms)
	text["summary"] = " ".join(filter(None, (text["camera"], text["action"]))).strip()
	return text


# Colour words translated by a fixed table (the model reads "hồng", pink, as red). Longest first: "xanh lá" before "xanh".


def translate(text, project, about="", earlier=""):
	"""Faithful English translation, given what the advertisement is about.

	Without context the planner model mistranslates product words ("giay" as leaves, "rut giay" as drawing) and short
	cues ("tiếng cốc đổ", a glass falling over, as "pouring water"); `about` is the scene the text belongs to.
	"""
	text = str(text or "").strip()
	if not text or looks_english(text):
		return text
	from joymedia.services.intake.references import brand

	references = ", ".join(row.label for row in project.selected_media or [] if row.label)
	story = " ".join(str(brand(project).get("logline") or "").split())[:400]
	context = (
		f"This is a storyboard for an advertisement for: {project.product_name or project.project_name}. "
		+ (f"The story: {story} " if story else "")
		+ f"Characters and products shown: {references or 'not specified'}. Product words refer to the advertised "
		"product; a character named in the text is the listed character, and a body part named in the text "
		"(for example a hand) belongs to that character."
		+ (f" The text belongs to this scene: {about}" if about else "")
		# What happened just before: "lấy thêm bánh" (more biscuits) needs the previous scene's "bánh quy".
		+ (f" Earlier in the film: {earlier}" if earlier else "")
		+ (f" Terms: {'; '.join(colour_terms(text))}." if colour_terms(text) else "")
	)
	prompt = (
		f"{context}\nTranslate this storyboard text into English. Be literal and complete; do not add, remove or "
		"change any detail, and do not repeat the original text.\n"
		f'TEXT: {text}\nReturn {{"english": "..."}}'
	)
	for attempt in range(2):
		raw = _ask_planner(
			prompt
			+ (
				"\nThe answer must be written in English only, not in the original language."
				if attempt
				else ""
			),
			system="You translate storyboard text faithfully. Return JSON only.",
			sampling_profile="scene_translation",
			capability="translator",
		)
		english = english_part((raw or {}).get("english"))
		# A complete translation is about as long as the text: much shorter drops an action, much longer invents one.
		if (
			english
			and is_english(english)
			and 0.5 * len(text) <= len(english) <= 2.2 * len(text) + 40
			and not invented_names(english, f"{text} {about} {project.product_name or ''}")
		):
			return english
	# A long text the model would not translate is translated a sentence at a time; a sentence it still cannot
	# translate is left out rather than sent to the video model in Vietnamese.
	sentences = [x.strip() for x in re.split(r"(?<=[.!?;])\s+|\n+", text) if x.strip()]
	if len(sentences) > 1:
		done = [translate(sentence, project, about) for sentence in sentences]
		kept = [x for x in done if is_english(x)]
		if kept:
			return " ".join(kept)
	elif sentences:
		# One sentence: try again without its parenthesised aside, which often confuses the translation.
		bare = re.sub(r"\s*\([^)]*\)", "", sentences[0]).strip()
		if bare and bare != sentences[0]:
			return translate(bare, project, about)
	return text


def audio_direction(project, beat, foley=None):
	"""The beat's sound direction as a workflow-neutral `Audio:` line.

	A workflow may generate its soundtrack (effects, music) from the prompt in the form of an `Audio:` line.
	A planned video prompt replaces the storyboard text, so without this the
	scene's sound effects would silently disappear. Voice-over is recorded separately and is not included.
	"""
	from joymedia.services.audio.plan import parse_audio_cues

	# In the sound-effect modes the sheet's music (BGM) direction is left out: the film carries effects only.
	effects_only = (project.get("soundtrack_mode") or "Sound effects only") != "Full soundtrack"
	parts = [
		f"{'sound effects' if role == 'SFX' else 'music'}: {translate(text, project, about=beat.get('action') or '')}"
		for role, text in parse_audio_cues(beat.get("audio"))
		if role == "SFX" or not effects_only
	]
	if not parts and foley:
		# The beat names no sound: use the planner's description of the physical sounds of the action.
		parts = [f"sound effects: {foley.rstrip('. ')}"]
	return f"Audio: {'; '.join(parts)}." if parts else ""


BRAND_PROMPT = (
	("logline", "STORY"),
	("key_message", "KEY MESSAGE"),
	("audience", "AUDIENCE"),
	("claims", "APPROVED CLAIMS (the only product benefits that may be shown or said)"),
	("avoid", "MUST NOT SAY OR SHOW"),
	("mandatories", "MUST INCLUDE"),
)


def brand_lines(project):
	"""The Brand sheet for the planner: the story, the message and what may, may not and must be shown."""
	from joymedia.services.intake.references import brand

	given = brand(project)
	return [
		f"{title}: {' | '.join(line.strip() for line in str(given[key]).splitlines() if line.strip())}"
		for key, title in BRAND_PROMPT
		if given.get(key)
	]


def previous_coverage(project, shot):
	"""Context for editorial decisions in both workbook and creative planning."""
	if int(shot.shot_number or 0) <= 1:
		return ""
	previous = frappe.db.get_value(
		"Shot",
		{"media_project": project.name, "shot_number": int(shot.shot_number) - 1, "is_removed": 0},
		"motion_plan_json",
	)
	if not previous:
		return ""
	plan = frappe.parse_json(previous) if isinstance(previous, str) else previous
	structure = plan.get("shot_structure") if isinstance(plan, dict) else None
	return (
		"PREVIOUS COVERAGE (preserve axis; motivate repeated size or a large jump): " + json.dumps(structure)
		if structure
		else ""
	)


def build_planning_prompt(project, shot, beat, references, previous_end_state):
	from joymedia.services.planning.camera import camera_planning_rules
	from joymedia.services.planning.director_rules import CINEMATOGRAPHY_RULES
	from joymedia.services.planning.shot_structure import PLANNING_RULES as SHOT_STRUCTURE_RULES
	from joymedia.services.project.formats import ratio_label
	from joymedia.services.scene.contract import PLANNING_RULES

	aspect = (
		ratio_label(project.delivery_width, project.delivery_height) or "unspecified; do not invent a format"
	)
	lines = (
		[
			f"PROJECT: {project.product_name or project.project_name}. Format: {aspect}.",
			f"BRIEF: {' '.join(str(project.video_idea or '').split())[:300]}",
			"AVAILABLE REFERENCES (use only these keys):",
			*(
				f"- {ref['key']}: {ref['label']} ({ref['role']})"
				+ (f". It shows: {ref['description']}" if ref.get("description") else "")
				for ref in references
			),
		]
		if references
		else [
			f"PROJECT: {project.product_name or project.project_name}. Format: {aspect}.",
			f"BRIEF: {' '.join(str(project.video_idea or '').split())[:300]}",
			"AVAILABLE REFERENCES: none.",
		]
	)
	lines.append(previous_coverage(project, shot))
	lines += brand_lines(project)
	lines.append(camera_planning_rules(project))
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
		"is in plain words, for example 'the mascot' or 'the product pack', never by its file label or "
		"brand name, and never copy the beat's wording or the role in brackets):",
		f"- The advertised product is: {project.product_name or project.project_name}. "
		"Distinguish the referenced retail package from its removable contents and from printed artwork. "
		"When the action handles a paper or tissue sheet, keep it a thin flexible sheet; never substitute "
		"the package or a toy for its contents. Bind only the actual advertised package to the package reference.",
		"- image_prompt: English, at most 60 words. Describe only the first frame: subjects, setting, framing, "
		"lighting. Include only what must appear. Preserve existing product artwork; add no captions or invented logos. Referenced subjects perform only the authored action with their own anatomy, proportions and physically supported pose; do not substitute human anatomy for a nonhuman reference.",
		"- setting_prompt: English, at most 30 words. Only the place, light and camera framing of the first frame: "
		"no character, animal, hand, product, object in action or text.",
		"- sound_effects: English, at most 15 words: the physical, non-vocal sounds this action makes (rustling, "
		"tearing, a thud, pouring). Never speech, laughter, singing or music.",
		"- Existing printed quantities, product names and artwork are controlled by the product image. "
		"Preserve those markings without translating or respelling them; invent no quantities, prices or claims.",
		"- video_prompt: English, at most 80 words. What moves and how the camera moves, in time order, as one "
		"continuous shot. Keep every action the beat requires; invent no claims or extra characters.",
		"- image_prompt is ONE still frame, never a sequence of events. When a reference shows a pose, keep the "
		"character's pose in the prompt consistent with it.",
		"- " + _locked_product_opening_rule(),
		"- Name a character only as the same subject its reference shows (for example 'the mascot'); never use a "
		"generic animal or person word, which makes the video model invent a "
		"different one.",
		"- The listed Character identities are the whole cast; alternate reference views of one identity are "
		"the same individual, never additional cast. A mother, mom or "
		"mama in the beat is the listed mother; a baby, kid, child or cub is the listed kid; a hand, arm or paw is "
		"that character's own (never a separate person's, never a different animal). Keep every action in the beat, "
		"even those before or after the main action.",
		"- reference_keys: include the key of EVERY listed character or product that is visible in the first frame "
		"(the advertised product's pack whenever the product itself is shown). Empty only if none is visible.",
		'- continuity_mode: "Continue" only if this beat continues the same scene, subject and setting from the '
		'previous shot; otherwise "New Scene".',
		"- needs_editing: if the beat needs several cuts, locations or a split-screen that one continuous clip "
		'cannot show, give a short reason and plan the single most important moment; else "".',
		"- motion_plan: actions with start and end in seconds covering the duration.",
		PLANNING_RULES,
		SHOT_STRUCTURE_RULES,
		CINEMATOGRAPHY_RULES,
		"",
		"Use the beat's own subjects and interactions; examples must never introduce unrelated props or actions.",
		"",
		'Return {"image_prompt":"","setting_prompt":"","sound_effects":"","video_prompt":"","reference_keys":[],"continuity_mode":"New Scene",'
		'"start_state":"","end_state":"","motion_plan":{"actions":[{"start":0,"end":0,"action":""}]},'
		'"needs_editing":""}',
	]
	return "\n".join(lines)


MIN_COVERAGE = 0.5
REVIEW_COVERAGE = 0.85


# Words in a reference's label that say what kind of image it is, not what it shows.
LABEL_FILLER = frozenset(
	"mascot character person model image photo picture pack package box background room reference".split()
)


def ground_reference_keys(project, beat, keys, references):
	"""Add the references a beat names in its own words, which the planner's guess can miss.

	- A product reference is added when the beat mentions the advertised product (matched on the
	  product's name, not on the model's guess).
	- Any other reference is added when the beat uses a distinctive word of the reference's own label
	  (for example, a distinctive label word shared with the beat).
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


PRODUCT_CONTAINER_WORDS = frozenset(
	"pack packet package box carton dispenser bottle tube pouch container product branded".split()
)


def _visible_package_words(text):
	"""Explicitly offscreen packages and negative instructions do not add visible inventory."""
	words = set()
	for clause in re.split(
		r"[.!?;,\n]+|\b(?:but|while)\b",
		str(text or "").split("Product orientation is locked", 1)[0],
		flags=re.I,
	):
		if re.match(
			r"\s*(?:no|without|never show|do not show)\s+(?:[\w-]+\s+){0,3}"
			r"(?:pack(?:et|age)?s?|box(?:es)?|cartons?|dispensers?|bottles?|tubes?|pouches?|containers?)\b",
			clause,
			re.I,
		) and not re.search(
			r"\b(?:but|however|yet|holds?|holding|carrying|carries|contains?)\b", clause, re.I
		):
			continue
		if re.search(
			r"\boff[- ]?(?:screen|camera)\b|\bout of (?:the )?(?:frame|view|shot)\b|\boutside (?:the )?(?:close[- ]?up|frame|view)\b",
			clause,
			re.I,
		):
			continue
		clause = re.sub(
			r"\b(?:no|without|never show|do not show)\s+(?:a\s+|any\s+|the\s+)?"
			r"(?:pack(?:et|age)?s?|box(?:es)?|cartons?|dispensers?|bottles?|tubes?|pouches?|containers?)\b",
			"",
			clause,
			flags=re.I,
		)
		words.update(_words(clause.casefold(), minimum=1))
	containers = PRODUCT_CONTAINER_WORDS - {"product", "branded"}
	return words & (containers | {name + "s" for name in containers} | {"boxes", "pouches"})


def _without_unauthored_package(image_prompt, notes, *, description="opening still"):
	"""Remove a package the planner carried into a scene whose roster has none.

	Unbound, the image model drew an invented branded bag for "holding a tissue
	pack". Ask once for the same opening still without any package; a loose
	item it names (a tissue) stays. Keep the planner's text if that fails.
	"""
	text = str(image_prompt or "")
	# The product-lock contract appended to a prompt is not the planner naming a package.
	if not _visible_package_words(text):
		return text
	# Omit a standalone world-state sentence about an off-camera package.
	# Preserve all other bytes/subjects rather than asking a model to invent
	# another object while rewriting an otherwise correct held-material state.
	clauses = re.split(r"(?<=[.!?;])\s+|\n+", text)
	package_subject = re.compile(
		r"^(?:Rules:\s*)?(?:(?:the|a|an)\s+)?"
		r"(?:(?!mascot\b|character\b|actor\b|person\b|child\b|bear\b|woman\b|man\b)[\w'-]+\s+){0,5}"
		r"(?:pack(?:age|et)?|box|carton|container|bottle|tube|pouch)\s+"
		r"(?:is|are|remains?|stays?|sits?|rests?)\b",
		re.I,
	)
	kept = [clause for clause in clauses if not package_subject.match(clause.strip())]
	cleaned = " ".join(kept).strip()
	if cleaned and len(kept) < len(clauses) and not _visible_package_words(cleaned):
		notes.append(f"Omitted off-camera package continuity from the {description}.")
		return cleaned
	try:
		answer = _ask_planner(
			f"Rewrite this {description} without any package, pack, box or container: this scene's script "
			"shows none. Keep every other subject, any loose item it names, the place, framing and each "
			"body's support. Preserve the action order and whether this is a starting or ending state. "
			"Return JSON image_prompt string. Source: " + text,
			system=f"You remove an unauthored product package from a {description}.",
			capability="planner",
			sampling_profile="production_plan",
			response_schema={
				"type": "object",
				"properties": {"image_prompt": {"type": "string"}},
				"required": ["image_prompt"],
				"additionalProperties": False,
			},
		)
		rewritten = " ".join(str((answer or {}).get("image_prompt") or "").split())
	except Exception:
		rewritten = ""
	if rewritten and not _visible_package_words(rewritten):
		notes.append(f"Removed a package the script does not show from the {description}.")
		return rewritten
	notes.append(f"The {description} names a package the script does not show.")
	return text


def ground_visible_product_keys(project, plan, keys, references, *, beat=None):
	"""Bind product source art whenever the resolved shot visibly contains its container.

	The writer can correctly describe a pack in ``image_prompt`` while omitting its
	reference key. That leaves the keyframe generator free to redraw branding and
	lettering. Beat-only grounding cannot catch this because the concrete opening
	composition appears only after production planning.
	"""
	# A scene with an explicit empty product roster may show a removed consumable
	# without its container. Generic product-lock instructions in the planner's
	# prompt are not evidence that the package belongs in that opening frame.
	if beat is not None and beat.get("products") == []:
		# Continuity may keep an off-camera pack stationary in the room. That
		# world state is not a reason to put it inside a declared product-free
		# close-up. Explicit visible handling still contradicts an empty roster.
		fields = (
			("camera", "action") if beat.get("products_declared") else ("raw", "camera", "action", "rules")
		)
		authored = " ".join(str(beat.get(field) or "") for field in fields)
		if beat.get("products_declared") and _visible_package_words(authored):
			raise ValueError(
				"The scene declares no visible product but its opening or action shows a package; repair the scene roster or staging."
			)
		if not _visible_package_words(authored):
			product_keys = {
				reference["key"] for reference in references if reference.get("role") == "Product"
			}
			notes = []
			for field, description in (
				("image_prompt", "opening still"),
				("start_state", "starting state"),
				("end_state", "ending state"),
				("video_prompt", "motion direction"),
			):
				if not plan.get(field):
					continue
				plan[field] = _without_unauthored_package(plan[field], notes, description=description)
				if _visible_package_words(plan[field]):
					raise ValueError(
						f"The {description} still introduces a package absent from the scene's product roster."
					)
			return [key for key in keys if key not in product_keys], notes
	text = " ".join(
		str(plan.get(field) or "") for field in ("image_prompt", "video_prompt", "start_state", "end_state")
	).casefold()
	words = _words(text)
	container = bool(words & PRODUCT_CONTAINER_WORDS)
	if not container:
		return keys, []
	product_rows = [reference for reference in references if reference.get("role") == "Product"]
	if not product_rows:
		return keys, []
	selected = set(keys)
	added = []
	for reference in product_rows:
		label_words = _words(reference.get("label") or "") - LABEL_FILLER
		product_words = _words(project.product_name or "")
		if label_words & words or product_words & words or len(product_rows) == 1:
			if reference["key"] not in selected:
				added.append(reference["key"])
				selected.add(reference["key"])
	if not added:
		return keys, []
	return keys + added, [
		"Added locked product reference(s) because the resolved shot visibly names a product container."
	]


def normalize_production_shot(raw, *, reference_keys, duration, is_first):
	"""Validate the planner's answer. Unknown references are dropped and reported; the rest must be usable."""
	if not isinstance(raw, dict):
		frappe.throw(_("The planner returned an invalid production plan."))
	image_prompt = " ".join(str(raw.get("image_prompt") or "").split())[:MAX_PROMPT_CHARS]
	video_prompt = " ".join(str(raw.get("video_prompt") or "").split())[:MAX_PROMPT_CHARS]
	if not image_prompt or not video_prompt:
		frappe.throw(_("The planner did not return both an image prompt and a video prompt."))
	if len(image_prompt.split()) > MAX_IMAGE_WORDS:
		frappe.throw(
			_("The planner's image prompt is too long (maximum {0} words). Please replan this scene.").format(
				MAX_IMAGE_WORDS
			)
		)
	keys, notes = [], []
	for key in raw.get("reference_keys") if isinstance(raw.get("reference_keys"), list) else []:
		key = str(key).strip()
		if key in reference_keys and key not in keys:
			keys.append(key)
		elif key:
			notes.append(f"Ignored unknown reference '{key}'.")
	mode = (
		"Continue" if str(raw.get("continuity_mode") or "").strip().casefold() == "continue" else "New Scene"
	)
	motion = _normalized_motion_plan(raw.get("motion_plan"), duration, video_prompt)
	if any(a["end"] <= a["start"] or a["start"] < 0 or a["end"] > duration + 0.01 for a in motion["actions"]):
		motion["actions"] = [{"start": 0, "end": duration, "action": video_prompt}]
		notes.append("Motion timing was invalid and was replaced with one action.")
	needs_editing = " ".join(str(raw.get("needs_editing") or "").split())
	if needs_editing:
		notes.append(f"Needs editing: {needs_editing}")
	return {
		"image_prompt": image_prompt,
		"video_prompt": video_prompt,
		"reference_keys": keys,
		"setting_prompt": " ".join(str(raw.get("setting_prompt") or "").split())[:300],
		"sound_effects": " ".join(str(raw.get("sound_effects") or "").split())[:160],
		"continuity_mode": "New Scene" if is_first else mode,
		"start_state": " ".join(str(raw.get("start_state") or "").split())[:300],
		"end_state": " ".join(str(raw.get("end_state") or "").split())[:300],
		"motion_plan": motion,
		"notes": notes,
	}


def apply_production_shot(project, shot, plan):
	"""Write the planned prompts, continuity and references onto the shot; timing and copy are untouched."""
	from joymedia.api.storyboard import _assign_shot_references

	shot.image_prompt = plan["image_prompt"]
	shot.setting_prompt = plan.get("setting_prompt", "")
	shot.generation_prompt = plan["video_prompt"] + (f"\n\n{plan['audio']}" if plan.get("audio") else "")
	shot.motion_plan_json = frappe.as_json(plan["motion_plan"])
	shot.flags.explicit_motion_plan = True
	shot.start_state, shot.end_state = plan["start_state"], plan["end_state"]
	shot.continuity_mode = plan["continuity_mode"]
	shot.planner_notes = "\n".join(plan["notes"])
	shot.views_json = frappe.as_json(plan["views"]) if plan.get("views") else ""
	shot.save(ignore_permissions=True)
	_assign_shot_references(
		project, {shot.name: plan["reference_keys"]}, view_keys=plan.get("reference_views")
	)
	beat = creative_beat(project, shot)
	for field, frame_role in (("opening_reference", "first_frame"), ("ending_reference", "last_frame")):
		opening = beat.get(field)
		if not opening:
			continue
		from joymedia.api.storyboard import set_project_shot_keyframe
		from joymedia.services.intake.references import find_reference

		options = [
			{"key": row.reference_key, "label": row.label, "version": row.asset_version}
			for row in project.selected_media or []
		]
		ref = find_reference(opening, options)
		if not ref:
			frappe.throw(_("Opening reference '{0}' is not selected in this project.").format(opening))
		set_project_shot_keyframe(project.name, shot.name, frame_role, ref["version"])
	_constrain_to_first_frame(project, shot, plan)


def _constrain_to_first_frame(project, shot, plan):
	"""Rewrite the movement so it names only what the first frame (the pasted references) contains."""
	from joymedia.services.keyframes.overlay import pasted_references
	from joymedia.services.planning.prompts import first_frame_inventory

	shot.reload()
	if plan.get("views"):
		return  # a split screen keeps its list of views as translated
	references = [
		{"reference_role": row.reference_role, "asset_version": row.asset_version}
		for row in shot.generation_inputs or []
	]
	if not pasted_references(
		references, shot.character_mode or project.get("character_mode") or "Paste exact art"
	):
		return
	project_labels = {row.asset_version: row.label for row in project.selected_media or []}
	inventory = first_frame_inventory(
		frappe._dict(
			references=references, character_mode=shot.character_mode or project.get("character_mode")
		),
		frappe._dict(
			references=[{"asset_version": v, "label": label} for v, label in project_labels.items()]
		),
	)
	# The sheet's camera line and its rules are not movement to rewrite: they are kept apart and put back as they are.
	body, _rules_sep, rules = plan["video_prompt"].partition("\n\nRules: ")
	action, _sep, camera = body.partition(" Camera: ")
	movement = faithful_rewrite(project, action, project_reference_options(project), inventory)
	movement += f" Camera: {camera}" if camera else ""
	movement += f"\n\nRules: {rules}" if rules else ""
	if movement != plan["video_prompt"]:
		shot.generation_prompt = movement + (f"\n\n{plan['audio']}" if plan.get("audio") else "")
		shot.save(ignore_permissions=True)


def request_seed(*parts):
	import hashlib

	return int(hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:8], 16)


CACHE_SECONDS = 7 * 24 * 3600


def _ask_planner(
	prompt,
	*,
	system=SYSTEM_PROMPT,
	max_tokens=None,
	refresh=False,
	capability="planner",
	sampling_profile="production_plan",
	response_schema=None,
):
	"""Ask the planner; an identical request returns the stored answer.

	The model is not deterministic even at temperature 0, so re-planning an unchanged beat would give a
	different plan each time. Answers are cached in Frappe's cache keyed by the exact request; pass
	refresh=True (or change the beat, references or brief) for a fresh one.
	"""
	settings = sampling(sampling_profile)
	max_tokens = settings["max_tokens"] if max_tokens is None else max_tokens
	from joymedia.services.runtime.endpoints import endpoint

	configured = endpoint(capability)
	cache_settings = {
		**settings,
		"service": {
			key: configured.get(key) for key in ("base_url", "model", "revision", "structured_output")
		},
	}
	if response_schema:
		cache_settings["response_schema"] = response_schema
		cache_settings["schema_context_version"] = 1
	cache_key = f"joymedia_{capability}:{request_seed(system, prompt, str(max_tokens), json.dumps(cache_settings, sort_keys=True))}"
	if not refresh:
		cached = frappe.cache.get_value(cache_key)
		if cached is not None:
			return cached
	schema_options = {"response_schema": response_schema} if response_schema else {}
	answer = _request_planner(
		prompt,
		system=system,
		max_tokens=max_tokens,
		capability=capability,
		sampling_profile=sampling_profile,
		**schema_options,
	)
	frappe.cache.set_value(cache_key, answer, expires_in_sec=CACHE_SECONDS)
	return answer


# vLLM sends nothing while it compiles a new JSON schema (81 s observed once), so
# the idle limit must exceed that; a lost request is still noticed in 2 minutes.
PLANNER_IDLE_SECONDS = 120


def _planner_completion(base_url, payload, timeout):
	"""Return (response, content); a lost connection is asked once more.

	The request carries a fixed seed, so asking again gives the same answer.
	"""
	from joymedia.services.runtime.streaming import post_streamed

	for attempt in range(2):
		try:
			return post_streamed(
				f"{base_url}/chat/completions",
				payload,
				idle_seconds=PLANNER_IDLE_SECONDS,
				deadline_seconds=timeout,
			)
		except requests.RequestException as exc:
			if attempt:
				raise
			frappe.logger("joymedia.planner").warning("Planner answer lost (%s); asking once more.", exc)


def _request_planner(
	prompt,
	*,
	system,
	max_tokens,
	capability="planner",
	sampling_profile="production_plan",
	response_schema=None,
):
	from joymedia.services.runtime.endpoints import endpoint

	configured = endpoint(capability)
	base_url, model, timeout = configured.base_url, configured.model, configured.timeout
	if response_schema:
		# Constrained decoding supplies syntax, not semantic field descriptions
		# to a local model's context. Keep those instructions visible regardless
		# of the configured structured-output transport.
		system += (
			"\nReturn JSON following this output schema, including its field descriptions:\n"
			+ json.dumps(response_schema, ensure_ascii=False, separators=(",", ":"))
		)
	payload = {
		"model": model,
		"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
		"response_format": {"type": "json_object"},
		**sampling(sampling_profile),
		# The same request gives the same plan: the seed follows the prompt, not the clock.
		"seed": request_seed(system, prompt),
		"max_tokens": max_tokens,
	}
	if response_schema:
		from joymedia.services.runtime.endpoints import structured_response

		payload.update(structured_response(configured, response_schema, "production_script"))
	if capability in {"planner", "writer"}:
		from joymedia.services.planning.plan_parsing import _completion_budget

		payload["max_tokens"] = _completion_budget(base_url, payload)
	from joymedia.vendor.open_storyline.parse_json import parse_json_dict

	for attempt in range(2):
		if attempt:
			# A deterministic invalid completion needs a different seed.
			payload["seed"] = request_seed(system, prompt, "json-retry")
		try:
			response, content = _planner_completion(base_url, payload, timeout)
		except requests.RequestException as exc:
			raise PlannerUnavailableError(
				_("The planner is unavailable at {0}: {1}").format(base_url, str(exc))
			) from exc
		if not response.ok:
			if response.status_code == 429 or response.status_code >= 500:
				raise PlannerUnavailableError(
					_("The planner is temporarily unavailable ({0}): {1}").format(
						response.status_code, response.text[:300]
					)
				)
			frappe.throw(
				_("The planner request failed ({0}): {1}").format(response.status_code, response.text[:300])
			)
		try:
			return parse_json_dict(content)
		except (KeyError, IndexError, TypeError, ValueError) as exc:
			if attempt:
				frappe.throw(_("The planner returned invalid JSON after retry: {0}").format(str(exc)))
			frappe.logger("joymedia.planner").warning("Planner JSON parse failed; retrying with a new seed.")
