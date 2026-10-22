"""References -> varied, timed JoyMedia scripts, using the existing planner.

No product names, action examples, aspect ratio or model selection live here.
Creative output is validated input to the ordinary workbook production path.
"""

import copy
import io
import json
import math
import re

import frappe

from joymedia.services.planning.script_review import review_script_actions
from joymedia.services.planning.shot_structure import (
	ANGLES,
	CAMERA_MOVES,
	FRAMINGS,
	MOTIONS,
	MOVE_BEHAVIOR,
	SHOT_GUIDE,
	STAGES,
)
from joymedia.services.planning.timed_actions import normalize_action_separators, read_timed_actions

CREATIVE_INVARIANTS = (
	"Preserve reference identities, observed product construction, explicit format/duration and approved claims. "
	"Select a concrete supplied view key whose visible pose, anatomy and surfaces suit each action; preserve that view choice through repairs. Alternate views remain one identity. "
	"Choose a supplied pose and support compatible with the action; show any necessary change of support before travel. Do not describe walking while the subject remains seated or attached to stationary furniture. "
	"Keep one coherent interaction per shot, chronological prerequisites and persistent object/support states. "
	"Invent no opening mechanism. Extracted consumables remain outside their unused stock; do not reset the story by putting them back. "
	"Do not invent a performance test or effect that the approved claims do not support; visible material handling is enough. "
	"Name every ordinary prop and action target before use. Non-final shots advance tangible object/action state, not prolonged looking or posing. "
	"A real change of material form, object location or contact is tangible progress. The final branded presentation may hold briefly. "
	"Use purposeful coverage and action-driven phase timings, with camera behavior derived from semantic structure."
)

UNANCHORED_PHYSICAL_EFFECT = re.compile(
	r"\b(?:water|liquid|spill|stain|dust|dirt|grime|clean|polish|soak|absorb|wet|dip|pour|rinse|tear|stretch|break)\w*\b",
	re.I,
)
# The style is appended to every picture prompt, including empty-place drawings:
# naming subjects there puts extra characters or products into the set.
STYLE_SUBJECT = re.compile(
	r"\b(?:mascots?|characters?|people|persons?|humans?|animals?|toys?|products?|packag\w*|packs?|logos?)\b",
	re.I,
)
# Reference analysis states construction as "Visible construction: flexible|rigid".
RIGID_CONTAINER = re.compile(
	r"\b(?:box|boxes|carton|cartons|lid|lids|crate|tin|jar|bottle|can)\b|\b(?:peel\w*|unseal\w*|seal|protective film|shrink[- ]?wrap)\b",
	re.I,
)
STATE_RESET = re.compile(
	r"\b(?:put|puts|place|places|return|returns|tuck|tucks|stuff|stuffs|push|pushes)\b[^.;\n]*\bback\s+(?:in|into|inside)\b",
	re.I,
)
EDITORIAL_TEXT = re.compile(
	r"\b(?:on[- ]screen text|text (?:appears|overlay|pops up)|captions? appears?|title card)\b", re.I
)
BODY_PART = re.compile(r"\b(?:hands?|fingers?|arms?|palms?)\b", re.I)
MONTAGE = re.compile(
	r"\b(?:split[- ]?screens?|montage|various (?:situations|places|locations|settings|scenes)|several (?:situations|places|locations))\b",
	re.I,
)
ANONYMOUS_HUMAN = re.compile(
	r"\b(?:an?|the)\s+(?:(?:off[- ]screen|unseen|human)\s+){0,2}(?:hand|arm|person|human|man|woman|adult|child|kid|boy|girl|someone|customer|user|mother|father)\b"
	# Groups of people are just as absent from the references as one stranger.
	r"|\b(?:an?|the|their|his|her|its|whole|some)\s+(?:\w+\s+){0,2}(?:family|families|people|children|kids|friends|parents|guests|crowd|couple|mom|dad|baby|toddler|teenagers?)\b(?![-\s]+(?:room|size|pack|car|table|kitchen|home|dining|living|house|sofa|couch|photo|album|style|meal|dinner|breakfast))",
	re.I,
)
# A mess the product cleans up must happen on camera first; a still picture cannot
# stage a spill that appears from nowhere, and viewers cannot follow it either.
MESS = re.compile(
	r"\b(?:spill(?:s|ed|ing)?|stain(?:s|ed)?|mess(?:y|es)?|crumbs|splash(?:es|ed)?|drips?|puddles?)\b", re.I
)
MESS_EVENT = re.compile(
	r"\b(?:spills|spilled|spilling|spill(?:s)?\s+(?:over|out)|tips?\s+over|knocks?\s+over|drops?|splash(?:es|ed)|drips|dripping|smears|leaks|overflows?)\b",
	re.I,
)
# A continuity rule that keeps a subject in place contradicts an action that moves it;
# the video model cannot satisfy both and the visual check then rejects the clip.
STAY_RULE = re.compile(
	r"\b(?:remains?|stays?|keeps?)\s+(?:seated|sitting|standing\s+still|still|in\s+place|"
	r"(?:on|in|at)\s+(?:the\s+)?(?:couch|sofa|chair|bed|floor|table|seat|spot))\b",
	re.I,
)
LOCOMOTION = re.compile(
	r"\b(?:walks?|walking|approach(?:es|ing)?|steps?|stepping|enters?|crosses|runs?|jumps?|hops?|climbs?|"
	r"(?:stands?|gets?)\s+up|moves?\s+(?:to|towards|toward|across|over))\b",
	re.I,
)
CLOSING_BEAT = re.compile(r"\b(?:pack\s?shot|cta|call to action|end card|closing shot)\b", re.I)
PASSIVE_OPENING = re.compile(
	r"\b(?:seen|look|looks|looking|spot|spots|smile|smiles|nod|nods|sit|sits|sitting|stand|stands|standing|hold|holds|holding)\b",
	re.I,
)
TANGIBLE_ACTION = re.compile(
	r"\b(?:pick|place|set|lift|grip|grab|pull|extract|unfold|fold|wipe|rub|dab|pat|blot|touch|apply|absorb|carry|turn|open|slide|tap|press|unwrap|wear|put|move|push|drop|rotate)\w*\b",
	re.I,
)

# Conservative causal precheck for an item explicitly acquired *later* from a
# source after an earlier shot already used that same named item. The screenplay
# writer uses English production prose; nouns come from the screenplay, never a
# product-specific list. The semantic reviewer remains responsible for cases
# that this narrow textual check cannot prove.
SOURCE_ACQUISITION = re.compile(
	r"\b(?:extracts?|pulls?|removes?|takes?|draws?|lifts?)\b(?P<object>[^.;\n]{0,100}?)\b(?:from|out of)\b",
	re.I,
)
MATERIAL_USE = re.compile(
	r"\b(?:press|wipe|dab|apply|wear|unfold|fold|clean|dry|rub|use|spread|touch)\w*\b[^.;\n]{0,100}", re.I
)


def _later_acquisition_conflict(scenes):
	"""Return the first demonstrable use-before-acquisition pair, if any."""
	for later_index, scene in enumerate(scenes):
		for acquisition in SOURCE_ACQUISITION.finditer(scene.get("action") or ""):
			phrase = acquisition.group("object").strip().casefold()
			if re.search(r"\b(?:another|additional|second|more)\b", phrase) or not re.search(
				r"\bthe\b", phrase
			):
				continue
			tokens = re.findall(r"[a-z][a-z-]*", phrase)
			if not tokens:
				continue
			item = tokens[-1]
			if item in {"edge", "corner", "piece", "part", "fold", "top", "bottom"}:
				continue
			article_item = re.compile(
				r"\b(?:a|an|the|one|this|that)\s+(?:[a-z-]+\s+){0,3}"
				+ re.escape(item)
				+ r"\b(?=\s+(?:against|onto|on|with|to|into|across|over|under|from|at|in)\b|[.,;]|$)",
				re.I,
			)
			for earlier_index, earlier in enumerate(scenes[:later_index]):
				if any(
					article_item.search(use.group(0))
					for use in MATERIAL_USE.finditer(earlier.get("action") or "")
				):
					return earlier_index + 1, later_index + 1, item
	return None


def _validate_action_progress(scenes):
	"""Require a completed object interaction in each non-closing action shot.

	The near-ending close view may instead reveal product print. This check uses
	visible actions, independent of proposed narrative labels and model choice.
	"""
	for index, scene in enumerate(scenes[:-1]):
		if (
			index == len(scenes) - 2
			and scene.get("products")
			and scene.get("shot_framing") in {"close_up", "extreme_close_up"}
		):
			continue
		phases = read_timed_actions(scene["action"], scene["duration_seconds"])
		# A relative clause can describe a prop's initial location ("the pack
		# that is placed on the table") without the subject doing anything.
		# Such set dressing must not satisfy the action-progress contract.
		if not any(
			TANGIBLE_ACTION.search(
				re.split(r"\b(?:where|which|that)\b", phase["action"], maxsplit=1, flags=re.I)[0]
			)
			for phase in phases
		):
			next_action = scenes[index + 1]["action"]
			raise ValueError(
				f"Scene {index + 1} has no completed object or material action. "
				"Replace a camera-only reveal, preparation or reaction with a visible "
				"subject/product interaction completed in this shot (for example, a supplied actor places "
				"or grips the product). If the next shot performs that same interaction, "
				"shift the subsequent beats rather than repeating it. "
				"Faulty action: "
				+ json.dumps(scene["action"], ensure_ascii=False)
				+ "; next action: "
				+ json.dumps(next_action, ensure_ascii=False)
			)


ENGLISH_WORDS = re.compile(
	r"\b(?:the|and|with|your|you|for|now|buy|get|our|this|that|of|to|is|are|every|today)\b", re.I
)
VIETNAMESE = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)


# What viewers see or hear: written in English with the script, then translated
# into the viewers' language by one faithful pass; the description stays English.
VIEWER_FIELDS = ("voice_over", "on_screen_text")


def _foreign(text):
	"""Vietnamese wording, ignoring capitalised names ("Gấu Shera") that stay as written."""
	return VIETNAMESE.search(re.sub(r"\b[A-ZÀ-Ỹ][a-zà-ỹ]+\b", "", str(text or "")))


def _plain(text):
	return " ".join(re.sub(r"[^\w]+", " ", str(text or "").casefold()).split())


def _place_frames(sheet, header_row, column, pictures, lang):
	"""Each scene's drawn first frame beside its row, as a small embedded picture."""
	from openpyxl.drawing.image import Image as SheetImage
	from PIL import Image

	cell = sheet.cell(header_row, column, "Khung hình đầu" if lang == "vi" else "First frame")
	sheet.column_dimensions[cell.column_letter].width = 24
	for number, path in sorted(pictures.items()):
		with Image.open(path) as image:
			image = image.convert("RGB")
			image.thumbnail((160, 240))
			buffer = io.BytesIO()
			image.save(buffer, "PNG")
			height = image.height
		picture = SheetImage(buffer)
		row = header_row + int(number)
		sheet.row_dimensions[row].height = max(sheet.row_dimensions[row].height or 15, height * 0.75 + 6)
		sheet.add_image(picture, sheet.cell(row, column).coordinate)


def _ratio_text(text):
	"""An authored format such as "Dọc 9:16" as "9:16", or "" when it names no ratio."""
	from joymedia.services.project.formats import parse_ratio, ratio_label

	ratio = parse_ratio(str(text or ""))
	return ratio_label(*ratio) if ratio else ""


def script_exemplars(file_names, index=0, *, scene_chars=520):
	"""Client-authored example workbooks -> compact style examples for the writer.

	Examples teach structure, pacing, tone and how the client writes voice-over and
	on-screen text. The writer gets a new premise; their selling points are client
	claims. The primary example rotates with the variant so variants differ.
	"""
	from joymedia.services.planning.workbook import parse_storyboard_workbook

	examples, claims, formats = [], [], set()
	for name in file_names or []:
		path = frappe.get_doc("File", name).get_full_path()
		for demo in parse_storyboard_workbook(path)["demos"]:
			if not demo.get("scenes"):
				continue
			meta = demo.get("metadata") or {}
			formats.add(_ratio_text(meta.get("format")))
			claims.extend(
				line.strip(" -•") for line in str(meta.get("usp") or "").splitlines() if line.strip(" -•")
			)

			def clip(value, limit):
				value = " ".join(str(value or "").split())
				return value if len(value) <= limit else value[: limit - 1] + "…"

			examples.append(
				{
					"product": clip(meta.get("product_name"), 80),
					"duration": meta.get("duration") or "",
					"tone": clip(meta.get("tone_mood"), 120),
					"scenes": [
						{
							"beat_name": clip(s.get("beat_name"), 50),
							"seconds": round(float(s.get("duration_seconds") or 0), 1),
							# Shot size and VO style only: full example actions get copied as a story.
							"visual_camera": clip(s.get("visual_camera"), scene_chars // 6),
							"voice_over": clip(s.get("voice_over"), 90),
							"on_screen_text": clip(s.get("on_screen_text"), 50),
						}
						for s in demo["scenes"][:8]
					],
				}
			)
	if not examples:
		return {}
	start = index % len(examples)
	ordered = examples[start:] + examples[:start]
	voice_lines = [
		_plain(s.get(field))
		for e in examples
		for s in e["scenes"]
		for field in ("voice_over", "on_screen_text")
		if len(_plain(s.get(field))) > 8
	]
	return {
		"screen_lines": [
			s["on_screen_text"] for e in examples for s in e["scenes"] if s.get("on_screen_text")
		],
		"language": "Vietnamese" if len(VIETNAMESE.findall(" ".join(voice_lines))) > 20 else "English",
		# The client's authored format, when every example states the same one.
		"format": next(iter(formats)) if len(formats) == 1 and all(formats) else None,
		"voice_lines": voice_lines,
		# The first example in full, the rest as beat outlines, to stay inside the writer's context.
		"examples": [ordered[0]]
		+ [{"product": e["product"], "beats": [s["beat_name"] for s in e["scenes"]]} for e in ordered[1:3]],
		"claims": list(dict.fromkeys(claims))[:12],
	}


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
					"description": " ".join(
						filter(
							None,
							[
								analysis.get("description", ""),
								("Visible pose/support: " + analysis["pose_and_support"])
								if analysis.get("pose_and_support")
								else "",
								("View constraint: " + view.keep_rule) if view.keep_rule else "",
							],
						)
					),
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
		"description": "Timed, tangible subject actions in order within one coherent interaction. Combine approach/reach with acquisition in one shot; separate acquisition, extraction and use when each completes a distinct action. No camera or on-screen text commands here.",
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
	for key, options in (
		("shot_framing", FRAMINGS),
		("shot_angle", ANGLES),
		("narrative_stage", STAGES),
		("camera_move", CAMERA_MOVES),
	):
		scene[key] = {"type": "string", "enum": sorted(options)}
	scene["camera_move"]["description"] = (
		"One of the six basic moves with its direction, or static: the move that best serves this beat."
	)
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
		"description": "Name at least two instruments or sound sources, tempo, and the visible beats where the arrangement changes; end with a resolved musical cadence. Avoid generic mood-only music text.",
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
	if len(weights) > 2 and all(w > 0 for w in weights):
		# Pacing is compiled here, not left to the model: a closing presentation
		# gets at most max(6 s, 20 %) and the rest goes back to the action scenes.
		share = max(6.0 / total, 0.2)
		others = sum(weights[:-1])
		weights[-1] = min(weights[-1], share * others / (1 - share))
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


def draft_script(
	project,
	*,
	nonce,
	previous=(),
	review_notes=(),
	examples=None,
	hero_product=None,
	revision=None,
	language=None,
	require_clean=False,
):
	"""Write one timed screenplay.

	Structural errors are repaired until valid (bounded). Heuristic story findings
	and the text reviewer get one rewrite; whatever remains is returned as
	`director_notes` for the person approving the script, instead of discarding
	an otherwise usable draft. Every rejected draft is kept as private evidence.
	"""
	from joymedia.services.intake.action_reference import action_observations
	from joymedia.services.intake.references import brand
	from joymedia.services.planning.camera import reference_camera_grammar
	from joymedia.services.planning.durations import _timeline_fps
	from joymedia.services.planning.production import _ask_planner
	from joymedia.services.planning.production import translate as translate_claims
	from joymedia.services.project.formats import ratio_label

	# Views remain selectable pose/construction anchors of one canonical identity.
	# The schema limits one view per identity per shot; collapsing them to the
	# first image would force a seated pose into a standing action.
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
	examples = examples or {}
	viewer_language = language or (examples or {}).get("language") or "English"
	camera_grammar = reference_camera_grammar(project) or {}
	claims = brand(project).get("claims") or ""
	claims_english = (
		translate_claims(
			claims,
			project,
			about="Approved product claims only; translate literally without adding benefits.",
		)
		if claims
		else ""
	)
	constraints = {
		"duration_seconds": project.total_duration_seconds or None,
		"fps": fps,
		# One shot, one generation: continuation segments would split a scene's
		# timed events across renders, which the visual check cannot verify.
		"max_scene_frames": capacity(workflow) if workflow else None,
		# The input decides the format (project settings, else the example scripts);
		# with neither, the writer proposes one with a reason. Never an assumed reel ratio.
		"aspect_ratio": ratio_label(project.delivery_width, project.delivery_height)
		or (examples or {}).get("format"),
		"approved_claims": claims or "Only directly visible product features.",
		"approved_claims_english": claims_english,
		"avoid": brand(project).get("avoid") or "",
		"mandatories": brand(project).get("mandatories") or "",
		"creative_direction": project.video_idea or "",
		"hero_product": hero_product or "",
		# Stock phrases ("Mua ngay") are shared vocabulary; only distinctive lines count as copies.
		"example_voice_lines": [line for line in examples.get("voice_lines") or [] if len(line.split()) >= 4],
		# The writer works in English; on-screen text is translated afterwards.
		"language": "English",
		"viewer_language": viewer_language,
		"client_examples": bool(examples.get("examples")),
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
		"historical_failure_patterns": [
			{"category": r.get("category", ""), "text": str(r.get("text") or "")[:320]}
			for r in review_notes
			if r.get("scope") == "Historical" and r.get("text")
		][:12],
	}
	roster = [
		{
			"key": item["key"],
			"role": item["role"],
			"label": item["label"],
			"keep_rule": item.get("keep_rule", "")[:400],
			"views": [
				{"key": view.get("key", item["key"]), "description": view["description"][:320]}
				for view in item["views"]
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
	constraints["action_reference_observations"] = observations
	effect_rule = (
		"Liquids, spills and cleaning appear only if the client examples or action observations use them; keep such an effect small and contained, with contact before the result. "
		if examples.get("examples") or observations
		else "No action reference was supplied: do not invent liquids, spills, stains, tearing or stretching; show direct handling and product detail instead. "
	)
	prompt = (
		"Write an ORIGINAL product commercial screenplay. "
		+ (
			"Follow the CLIENT EXAMPLE SCRIPTS for structure, pacing, tone, voice-over and on-screen text style (hook, problem, product use, benefit, packshot with CTA), but invent a new premise; never copy their story, products or cast. "
			if examples.get("examples")
			else "Use a classic structure: hook, problem, product use, benefit, packshot with CTA. "
		)
		+ "Write every field in English (examples may be in another language; never copy their wording). "
		+ (
			f"voice_over and on_screen_text (including the CTA) will be translated into {viewer_language} for the viewers: keep them short. "
			if viewer_language != "English"
			else ""
		)
		+ SHOT_GUIDE
		+ " "
		"RULES: "
		"1) Use roster keys only in cast and products; in prose describe subjects visually (e.g. 'the bear mascot'), never by key. Each identity is exactly ONE subject; its view keys are alternative poses, never additional characters. Choose the supplied pose that supports the action and keep one view per identity in a scene. Only roster actors appear in prose and cast (example scripts' characters do not exist here); no human or hand unless a Person is supplied. "
		"2) Every shot that shows the hero product uses the same roster product; never change its package, colour, print or construction. Do not translate or invent printed words. Once a consumable piece has been physically removed, a close action shot of only that detached piece and the actor may leave products empty so the image generator does not introduce a second container. Keep the product reference in any shot where the package or hero object is actually visible, especially the opening and final packshot. "
		"3) The supplied characters are the protagonists who perform the product actions. Open on a visible event already happening. Each non-final scene completes ONE tangible interaction (grip, take out, open, press, place, carry, apply...) with a visible result; combine reach and grab in one scene; no scene of only looking, posing or walking. "
		"4) Prerequisites first: take an item out before using it; used material never returns to the pack; objects keep their state across cuts. "
		"5) "
		+ effect_rule
		+ "6) Each scene is ONE continuous shot in ONE place: no split screens, montages or location changes inside a scene. A character keeps its weight on a support (floor or seat); one place keeps one identical description. "
		"7) The last scene is a stable product packshot with readable original print and the CTA from mandatories. For a static hero view, leave cast empty and place the original product on a real supporting surface so source artwork can remain exact; include a supplied actor in the closing shot only when that actor performs a meaningful visible product action. The on_screen_text field is only for an added viewer-facing overlay/CTA; do not transcribe or translate the physical package's logo, specifications or printed copy into that field. Source artwork owns those printed details. "
		"8) action is timed phases '[0-1.5s] ...' from 0 to the scene end, no gaps and no camera words. visual_camera is the opening composition only: a state one still picture can show. Preserve any grip, material location and support established by the preceding scene; never reset a carried product onto a table without placement. A new acquisition begins before its first contact, while an ongoing use begins in its retained state. Broad shots establish connected anatomy and support. Product close-ups show the focal material, original limb shape and contact area; the rest of the body may remain naturally outside the frame. Vary coverage with purpose. "
		"9) State only approved_claims from this product's brief; example scripts supply style, never product facts, certifications or performance claims. Sounds follow visible actions. Music must name concrete instruments, tempo and arrangement changes tied to visible beats, with a resolved ending; 'lively music' alone is insufficient. "
		"10) Give action scenes chronological beats completing one interaction and show each demonstration once. Choose scene count and phase timings from the requested duration, visible action and workflow frame capacity. Open with a supplied subject already completing a tangible product interaction; a camera moving toward a static product is not an action hook. Do not spend the hook on noticing, walking or waiting. Never pad with filler. Scene durations are relative weights. Write a different premise from PRIOR CONCEPTS. "
		"Historical failure patterns are warnings from older renders: avoid the same failure only if its action or object appears in this new concept. They do not authorize copying old scenes, props, claims or actors. "
		"Preserve explicit format/duration; if absent, propose them with a reason.\nCONSTRAINTS: "
		+ json.dumps({k: v for k, v in constraints.items() if k != "example_voice_lines"}, ensure_ascii=False)
		+ "\nREFERENCE KEY ROSTER: "
		+ json.dumps(roster, ensure_ascii=False)
		+ (
			"\nSAMPLED ACTION OBSERVATIONS: " + json.dumps(observations, ensure_ascii=False)
			if observations
			else ""
		)
		+ (
			"\nCLIENT EXAMPLE SCRIPTS: " + json.dumps(examples["examples"], ensure_ascii=False)
			if examples.get("examples")
			else ""
		)
		+ "\nPRIOR CONCEPTS: "
		+ json.dumps(list(previous), ensure_ascii=False)
		+ "\nVARIATION ID: "
		+ nonce
	)
	schema = script_schema(inventory, constraints)
	schema["properties"]["product_name"] = {
		"type": "string",
		"minLength": 1,
		"description": "Full product name with its specification, as printed or labelled.",
	}
	schema["properties"]["key_message"] = {
		"type": "string",
		"minLength": 1,
		"description": "The one sentence viewers must remember.",
	}
	schema["properties"]["audience"] = {
		"type": "string",
		"minLength": 1,
		"description": "Who the film is for.",
	}
	schema["required"] = [*schema["required"], "product_name", "key_message", "audience"]

	def finish(script, findings, advisory, wording, attempts):
		blocking = [row for row in findings["issues"] if row["category"] != "production_detail"]
		for row in findings["issues"]:
			if row.get("text_cross_check") or row["category"] != "production_detail":
				# A retracted omission is already covered by the action sequence;
				# repeating its requested action would introduce duplicate use.
				continue
			scene = script["scenes"][row["scene"] - 1]
			scene["continuity_rules"] += "\nProduction direction: " + row["instruction"]
		script = validate_script(script, inventory, constraints, [])
		script["camera_adjustments"] = direct_camera(script["scenes"], camera_grammar)
		script["action_review"] = findings
		script["director_notes"] = advisory + [
			f"Scene {row['scene']}: {row['instruction']}" for row in blocking
		]
		script["writer_attempts"] = attempts
		script["wording_adjustments"] = wording
		if claims:
			script["claims"] = constraints["approved_claims"]
		if viewer_language != "English":
			script = localize_viewer_text(
				script, viewer_language, examples=examples.get("screen_lines") or ()
			)
			validate_script(script, inventory, {**constraints, "language": viewer_language}, [])
		if require_clean and script.get("director_notes"):
			_save_rejected_drafts(
				project,
				nonce,
				[*rejected, {"attempt": attempts, "script": script, "findings": script["director_notes"]}],
			)
			raise ValueError(
				"Automatic screenplay still has unresolved director or translation findings; inspect the saved draft evidence before rendering."
			)
		return script

	error, latest_script, rejected, rewrite_budget = "", None, [], 5 if require_clean else 2
	best_valid = None
	if revision:
		# A reviewer's notes on an earlier script: edit that script, starting from the repair path.
		latest_script = {
			k: v for k, v in revision["script"].items() if k not in {"action_review", "director_notes"}
		}
		error = (
			"\nREVIEWER NOTES (apply every note; change only the scenes they name and copy every other scene unchanged): "
			+ json.dumps(revision["notes"], ensure_ascii=False)
		)
	for _attempt in range(6):
		if _attempt == 3:
			# Repairs to an invalid causal premise often preserve the same bad action
			# chain. Allow one fresh proposal before stopping the bounded job.
			latest_script = None
			error = "\nThe prior concept remained invalid after three repairs. Write a new premise and action chain that follows every invariant."
		request_prompt = prompt + error
		if latest_script is not None:
			# Edit the complete latest screenplay, rather than asking the creative
			# writer to invent another story from a detached list of action quotes.
			request_prompt = (
				"Edit the supplied complete screenplay to fix the quoted defects. Keep its premise, "
				"identities, format, duration and languages; replace any filler shot entirely when needed, "
				"and change its dependent "
				"opening/continuity/result text. Preserve chronological prerequisites across scenes. "
				"A later result must not be inserted into an earlier scene before acquisition/contact. "
				"Mechanical staging notes belong in continuity_rules. Return the complete schema.\n"
				+ "REFERENCE ROSTER: "
				+ json.dumps(roster, ensure_ascii=False)
				+ "\nCONSTRAINTS: "
				+ json.dumps(
					{
						k: v
						for k, v in constraints.items()
						if k not in {"unresolved_feedback", "example_voice_lines"}
					},
					ensure_ascii=False,
				)
				+ "\nLATEST SCREENPLAY: "
				+ json.dumps(
					{k: v for k, v in latest_script.items() if k != "timing_compilation"}, ensure_ascii=False
				)
				+ "\nDEFECTS TO REPAIR: "
				+ error
			)
		try:
			result = _ask_planner(
				request_prompt,
				system="You write complete multi-scene commercial scripts from visual product references. Return only the requested JSON, using exact enum values and reference keys. The primary user direction takes precedence over examples and motion observations.\nPRIMARY USER DIRECTION: "
				+ constraints["creative_direction"]
				+ "\nINVARIANTS FOR ORIGINAL WRITING AND EVERY REPAIR: "
				+ CREATIVE_INVARIANTS,
				sampling_profile="creative_script_repair" if latest_script is not None else "creative_script",
				capability="writer",
				response_schema=schema,
			)
		except (frappe.ValidationError, ValueError) as exc:
			if best_valid is None:
				raise
			rejected.append({"attempt": _attempt + 1, "error": str(exc)})
			break
		try:
			if revision:
				result = _keep_unnoted_scenes(result, revision)
			script = fit_generated_timing(
				result, constraints["duration_seconds"], fps, max_scene_frames=constraints["max_scene_frames"]
			)
			wording = (
				english_production_text(script, viewer_language)
				+ normalize_product_wording(script, inventory)
				+ normalize_product_camera_inserts(script)
				+ fresh_example_copies(script, constraints)
			)
			# Keep the complete proposal for repair even when semantic validation
			# rejects it; detached error messages otherwise recreate the same defect.
			latest_script = script
			advisory = []
			script = validate_script(script, inventory, constraints, advisory)
			latest_script = script
			try:
				findings = review_script_actions(
					script,
					roster,
					constraints["unresolved_feedback"],
					{
						k: constraints[k]
						for k in (
							"approved_claims",
							"approved_claims_english",
							"avoid",
							"mandatories",
							"camera_reference_notes",
							"creative_direction",
							"action_reference_observations",
							"historical_failure_patterns",
						)
					},
				)
			except ValueError as exc:
				# The reviewer failing its own quoting protocol is not a script defect.
				findings = {"coverage": [], "issues": []}
				advisory.append("Automatic text review could not run: " + str(exc)[:200])
			blocking = [row for row in findings["issues"] if row["category"] != "production_detail"]
			score = len(blocking) + len(advisory)
			if best_valid is None or score < best_valid[0]:
				best_valid = (score, copy.deepcopy((script, findings, advisory, wording)))
			# The last attempt never discards a valid script over review findings:
			# they become notes for the human review instead.
			if (blocking or advisory) and rewrite_budget and _attempt < 5:
				rewrite_budget -= 1
				rejected.append({"attempt": _attempt + 1, "script": script, "findings": advisory + blocking})
				error = (
					"\nRevise the complete script to fix these grounded issues in the LATEST draft: "
					+ json.dumps(advisory + findings["issues"], ensure_ascii=False)
					+ "\nREJECTED ACTION CHAIN: "
					+ json.dumps(
						[{k: scene[k] for k in ("duration_seconds", "action")} for scene in script["scenes"]],
						ensure_ascii=False,
					)
				)
				continue
			if require_clean and (blocking or advisory):
				rejected.append({"attempt": _attempt + 1, "script": script, "findings": advisory + blocking})
				continue
			return finish(script, findings, advisory, wording, _attempt + 1)

		except ValueError as exc:
			rejected.append({"attempt": _attempt + 1, "script": latest_script, "error": str(exc)})
			error += (
				f"\nRepair attempt {_attempt + 1}; return the complete script, correcting ALL accumulated errors: "
				+ str(exc)
			)
	_save_rejected_drafts(project, nonce, rejected)
	if require_clean and best_valid is not None:
		raise ValueError(
			"Automatic screenplay still has unresolved causal, claim or director findings after bounded repair; "
			"inspect the saved draft evidence before rendering."
		)
	if best_valid is not None:
		script, findings, advisory, wording = best_valid[1]
		script["writer_fallback"] = {
			"reason": "Later optional rewrites failed structural validation; retained the best structurally valid draft.",
			"quality_review": "deferred",
		}
		return finish(script, findings, advisory, wording, _attempt + 1)
	raise ValueError("Automatic script remained invalid after bounded repair: " + error)


def translate_lines(source, language, *, attempts=2, examples=(), keep=frozenset(), check=None):
	"""Faithfully translate a list of lines with the translator capability (same order and count)."""
	from joymedia.services.planning.production import _ask_planner

	schema = {
		"type": "object",
		"properties": {
			"lines": {
				"type": "array",
				"items": {"type": "string", "minLength": 1},
				"minItems": len(source),
				"maxItems": len(source),
			}
		},
		"required": ["lines"],
		"additionalProperties": False,
	}
	best = None
	for attempt in range(attempts):
		names = (
			"Keep the brand name; describe the product in English (e.g. its type, sheet count and ply)"
			if language == "English"
			else "Keep brand and product names"
		)
		result = _ask_planner(
			f"Translate each line into natural {language}. {names}, numbers and meaning exactly; "
			"keep each line as short as the original; do not add claims. "
			f"Return the lines in the same order.{' Every word must be ' + language + ' except the brand name.' if attempt else ''}"
			+ (
				"\nSTYLE OF THE CLIENT'S OWN ON-SCREEN TEXT: "
				+ json.dumps(list(examples)[:12], ensure_ascii=False)
				if examples
				else ""
			)
			+ "\nLINES: "
			+ json.dumps(source, ensure_ascii=False),
			system="You translate faithfully. Return only the requested JSON.",
			capability="translator",
			sampling_profile="scene_translation",
			response_schema=schema,
		)
		translated = result.get("lines") if isinstance(result, dict) else None
		if (
			isinstance(translated, list)
			and len(translated) == len(source)
			and all(isinstance(t, str) and t.strip() for t in translated)
		):
			best = [t.strip() for t in translated]
			# The language check is a heuristic: it earns a stricter retry, never a failure.
			if check is None or all(check(s, t) for s, t in zip(source, best, strict=True)):
				return best
	if best is not None:
		return best
	raise ValueError(f"The text could not be translated into {language}.")


def fresh_example_copies(script, constraints):
	"""Rewrite only the voice-over/on-screen lines copied verbatim from the client's examples.

	The examples teach tone; a copied line is a local defect, so it gets a line-level
	rewrite instead of a whole new script attempt.
	"""
	from joymedia.services.planning.production import _ask_planner

	examples = set(constraints.get("example_voice_lines") or [])
	targets, seen = [], set()
	for scene in script["scenes"]:
		for field in ("voice_over", "on_screen_text"):
			line = _plain(scene.get(field))
			# A copied example line, or a line already used by an earlier scene.
			if line and (line in examples or (field, line) in seen):
				targets.append((scene, field))
			seen.add((field, line))
	if not targets:
		return []
	source = [scene[field] for scene, field in targets]
	schema = {
		"type": "object",
		"properties": {
			"lines": {
				"type": "array",
				"items": {"type": "string", "minLength": 1},
				"minItems": len(source),
				"maxItems": len(source),
			}
		},
		"required": ["lines"],
		"additionalProperties": False,
	}
	for _attempt in range(2):
		result = _ask_planner(
			"These lines were copied from another commercial or repeat an earlier scene. Write a new line for each with the same purpose, "
			"language and length, for this product only; no wording reused from the original. "
			f"PRODUCT: {script.get('product_name') or ''}\nKEY MESSAGE: {script.get('key_message') or ''}"
			"\nLINES: " + json.dumps(source, ensure_ascii=False),
			system="You write short commercial copy. Return only the requested JSON.",
			capability="writer",
			sampling_profile="creative_script_repair",
			response_schema=schema,
		)
		lines = result.get("lines") if isinstance(result, dict) else None
		if (
			isinstance(lines, list)
			and len(lines) == len(source)
			and all(isinstance(t, str) and t.strip() and _plain(t) not in examples for t in lines)
			and len({_plain(t) for t in lines}) == len(lines)
		):
			for (scene, field), text in zip(targets, lines, strict=True):
				scene[field] = text.strip()
			return [f"Rewrote {len(targets)} copied or repeated line(s)."]
	return []


def english_production_text(script, viewer_language="English"):
	"""Translate non-English production text (the writer imitating foreign examples) into English.

	Production prompts are English; this is translation of external language, not
	a rewrite, so it costs no writer attempt.
	"""
	fields = (
		"beat_name",
		"visual_camera",
		"action",
		"visible_change",
		"place",
		"continuity_rules",
	)
	# Viewer lines are English here too when the viewers are English; otherwise the
	# viewer translation pass handles them.
	fields += VIEWER_FIELDS if viewer_language == "English" else ()
	targets = [(scene, f) for scene in script["scenes"] for f in fields if _foreign(scene.get(f))]
	targets += [(script, f) for f in ("visual_style", "music") if _foreign(script.get(f))]
	if not targets:
		return []
	lines = translate_lines(
		[holder[f] for holder, f in targets], "English", check=lambda s, t: not _foreign(t)
	)
	for (holder, field), text in zip(targets, lines, strict=True):
		holder[field] = text
	return [f"Translated {len(targets)} production field(s) into English."]


# One Vietnamese syllable written without tone marks ("MUA NGAY", "NHANH"); English words rarely fit.
VIETNAMESE_SYLLABLE = re.compile(
	r"(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdghklmnpqrstvx])?[aeiouy]{1,3}(?:ch|ng|nh|[cmnpt])?", re.I
)


def _untranslated(source, text, keep, language=None):
	"""English words of 4+ letters copied unchanged, other than brand/product names."""
	words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", source)} - keep
	if language == "Vietnamese":
		# Four-letter brand/design loanwords overlap Vietnamese copy; longer
		# untranslated source words still trigger a second translator attempt.
		words = {w for w in words if len(w) >= 5 and not VIETNAMESE_SYLLABLE.fullmatch(w)}
	return {w for w in re.findall(r"[A-Za-z]{4,}", text) if w.lower() in words}


def localize_viewer_text(script, language, attempts=2, examples=()):
	"""Translate what viewers see or hear (voice-over, on-screen text, CTA), faithfully.

	Writing the whole script in one language and translating only these lines is
	far more reliable than asking the writer to mix languages. English originals
	are kept for the reviewer.
	"""

	lines = [
		(scene, field)
		for scene in script["scenes"]
		for field in VIEWER_FIELDS
		if str(scene.get(field) or "").strip()
	]
	if not lines:
		return script
	source = [scene[field] for scene, field in lines]
	keep = {
		w.lower()
		for w in re.findall(
			r"[A-Za-z]{4,}", " ".join([script.get("product_name") or "", script.get("title") or ""])
		)
		if w[0].isupper()
	}

	def check(s, t):
		return len(ENGLISH_WORDS.findall(t)) < 2 and not _untranslated(s, t, keep, language)

	translated = translate_lines(source, language, attempts=attempts, examples=examples, check=check)
	script["viewer_text_source"] = {"language": "English", "lines": source}
	for (scene, field), text in zip(lines, translated, strict=True):
		scene[field] = text
	doubtful = [t for s, t in zip(source, translated, strict=True) if not check(s, t)]
	if doubtful:
		script.setdefault("director_notes", []).append(
			f"Check that this on-screen text reads naturally in {language}: " + " | ".join(doubtful)
		)
	return script


CAMERA_ROTATION = [
	"dolly_in",
	"truck_right",
	"pedestal_up",
	"pan_left",
	"tilt_up",
	"dolly_out",
	"truck_left",
	"pan_right",
]


def normalize_product_camera_inserts(script):
	"""Separate an AI camera-only packshot from its unchanged product state.

	This applies only when no actor is cast and every phase describes the camera.
	It cannot replace a requested interaction or silently remove actor actions.
	"""
	changes = []
	for index, scene in enumerate(script["scenes"], 1):
		phases = read_timed_actions(scene.get("action"), scene.get("duration_seconds"))
		if scene.get("cast") or not scene.get("products") or not phases:
			continue
		if not all(re.match(r"^(?:the\s+)?camera\b", phase["action"].strip(), re.I) for phase in phases):
			continue
		for phase in phases:
			phase["action"] = (
				"The original product stays in its opening position with unchanged visible artwork and support."
			)
		scene["action"] = "\n".join(
			f"[{phase['start']:.9f}-{phase['end']:.9f}s] {phase['action']}" for phase in phases
		)
		scene["visible_change"] = (
			"The original product remains in its declared position; its printed artwork is unchanged."
		)
		changes.append(
			f"Scene {index}: kept the product-only insert still; camera direction remains in camera_move."
		)
	return changes


PRODUCT_CONTAINER_WORDS = re.compile(r"\b(?:tissue\s+)?(box|boxes|carton|cartons)\b", re.I)


def normalize_product_wording(script, inventory):
	"""Call a flexible product a pack: a deterministic wording fix, not a rewrite.

	Invented lids, films or seals still go back to the writer (validate_script).
	"""
	changes = []
	label = r"^\s*(?:cta|call to action|on-screen text|text|vo|v\.o\.|voice[- ]?over|narrator|lời thoại)\s*[:\-–]\s*"
	for index, scene in enumerate(script["scenes"], 1):
		for field in VIEWER_FIELDS:
			text = scene.get(field) or ""
			bare = re.sub(label, "", text, flags=re.I)
			if bare != text:
				scene[field] = bare
				changes.append(f"Scene {index} {field}: removed the label from the viewer-facing text.")
	nouns = {
		"Character": "the character",
		"Person": "the person",
		"Product": "the product",
		"Logo": "the logo",
	}
	keys = {
		view.get("key", item["key"]): nouns.get(item["role"], "it")
		for item in inventory
		for view in item.get("views") or [{"key": item["key"]}]
		if re.search(r"[_\d]", view.get("key", item["key"]))
	}
	for index, scene in enumerate(script["scenes"], 1):
		for field in ("visual_camera", "action", "visible_change", "continuity_rules", "voice_over"):
			text = scene.get(field) or ""
			for key, noun in keys.items():
				text = re.sub(rf"(?<![\w])(?:the\s+)?{re.escape(key)}(?![\w])", noun, text, flags=re.I)
			if text != (scene.get(field) or ""):
				scene[field] = text
				changes.append(f"Scene {index} {field}: described subjects instead of naming reference keys.")
	style = script.get("visual_style") or ""
	if STYLE_SUBJECT.search(style):
		kept = [part for part in re.split(r"(?<=[,.;])\s+", style) if not STYLE_SUBJECT.search(part)]
		script["visual_style"] = (
			" ".join(kept).strip(" ,;") or "Soft directional lighting with a coherent palette."
		)
		changes.append("visual_style: removed subjects; style describes art direction only.")
	flexible = any(
		item["role"] == "Product"
		and any(
			"construction: flexible" in str(v.get("description") or "").lower()
			for v in item.get("views") or []
		)
		for item in inventory
	)
	if not flexible:
		return changes
	for index, scene in enumerate(script["scenes"], 1):
		for field in ("visual_camera", "action", "visible_change", "continuity_rules"):
			text = scene.get(field) or ""
			fixed = PRODUCT_CONTAINER_WORDS.sub(
				lambda m: "packs" if m.group(1).lower().endswith("s") else "pack", text
			)
			if fixed != text:
				scene[field] = fixed
				changes.append(f"Scene {index} {field}: called the flexible product a pack.")
	return changes


def vary_against_neighbours(scenes, index):
	"""Change only this scene's move when it repeats a neighbour or makes two statics in a row."""
	scene = scenes[index]
	if scene_motion(scene) in {"contact", "locomotion"}:
		return []
	neighbours = [scenes[i] for i in (index - 1, index + 1) if 0 <= i < len(scenes)]

	def coverage(s):
		return (s.get("shot_framing"), s.get("shot_angle"), s.get("camera_move", "static"))

	move = scene.get("camera_move", "static")
	if not any(
		coverage(n) == coverage(scene) or (move == "static" == n.get("camera_move", "static"))
		for n in neighbours
	):
		return []
	taken = {n.get("camera_move", "static") for n in neighbours}
	scene["camera_move"] = next(m for m in CAMERA_ROTATION if m not in taken)
	return [f"Scene {index + 1}: camera_move {move} -> {scene['camera_move']} (vary against its neighbours)."]


# A paw or hand working on the product: the camera holds still so contact stays readable.
CONTACT_ACTION = re.compile(
	r"\b(?:pull|extract|wipe|dab|blot|press|open|unfold|fold|grip|pick|lift|place|touch|tear|rub|hand|put|set|take)"
	r"(?:s|es|ed|ing)?\b",
	re.I,
)


def scene_motion(scene):
	"""What the subject does in the scene, which decides how the camera may move."""
	action, cast = scene.get("action") or "", scene.get("cast") or []
	if cast and (scene.get("subject_motion") == "locomotion" or LOCOMOTION.search(action)):
		return "locomotion"
	if cast and (scene.get("subject_motion") == "manipulation" or CONTACT_ACTION.search(action)):
		return "contact"
	if scene.get("products") and not cast:
		return "detail"
	return "other"


def direct_camera(scenes, grammar=None):
	"""Apply reference preferences by narrative job, with physical action first.

	An opening is not automatically an orbit and a CTA is not automatically a
	pull-back. Valid director choices survive unless precise contact or subject
	travel needs stable/following coverage. This applies to every product.
	"""
	changes = []
	preferences = (grammar or {}).get("moves") or {}
	move_for = {behavior: move for move, behavior in MOVE_BEHAVIOR.items()}

	def change(index, value, reason):
		old = scenes[index].get("camera_move")
		if old != value:
			changes.append(f"Scene {index + 1}: camera_move {old or 'unset'} -> {value} ({reason}).")
			scenes[index]["camera_move"] = value

	for index, scene in enumerate(scenes):
		motion = scene_motion(scene)
		if motion == "contact":
			change(index, "static", "keep physical contact readable")
		elif motion == "locomotion":
			change(index, "tracking", "follow subject travel")
		else:
			preference = preferences.get(scene.get("narrative_stage"), {})
			move = move_for.get(preference.get("behavior"))
			if move:
				change(index, move, "the supplied reference grammar for this narrative job")
			elif scene.get("camera_move") not in CAMERA_MOVES:
				change(index, "dolly_in" if motion == "detail" else "static", "fill a missing camera choice")
	return changes


def _keep_unnoted_scenes(result, revision):
	"""Reviewer notes on named scenes change only those scenes.

	Every other scene is copied verbatim from the reviewed script, so an approved
	scene never changes behind the reviewer's back. A whole-script note (no scene
	number) or a changed scene count leaves the rewrite as written.
	"""
	import copy

	noted = {n.get("scene") for n in revision["notes"]}
	old = revision["script"].get("scenes") or []
	if None in noted or not isinstance(result, dict) or len(result.get("scenes") or []) != len(old):
		return result
	result["scenes"] = [
		scene if index in noted else copy.deepcopy(old[index - 1])
		for index, scene in enumerate(result["scenes"], 1)
	]
	return result


def _save_rejected_drafts(project, nonce, rejected):
	"""Rejected drafts are private evidence for diagnosis, never an accepted script."""
	from frappe.utils.file_manager import save_file

	try:
		save_file(
			f"rejected-scripts-{nonce[:12]}.json",
			json.dumps(rejected, ensure_ascii=False, indent=1, default=str).encode(),
			"Media Project",
			project.name,
			is_private=1,
		)
		# The caller rolls back on the failure that follows; the evidence must survive it.
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="Could not keep rejected script drafts")


def validate_script(script, inventory, constraints, advisory=None):
	"""Structural errors always raise. Pass a list as `advisory` to collect the
	heuristic story findings (idle beats, unanchored effects) instead of raising;
	they then go to the human script review rather than stopping the batch."""
	from joymedia.services.project.formats import parse_ratio

	def heuristic(message):
		if advisory is None:
			raise ValueError(message)
		if message not in advisory:
			advisory.append(message)

	if (
		not isinstance(script, dict)
		or not isinstance(script.get("scenes"), list)
		or not 2 <= len(script["scenes"]) <= 12
	):
		raise ValueError("A script requires 2–12 scenes.")
	for key in ("title", "logline", "format", "format_reason", "visual_style", "music"):
		if not isinstance(script.get(key), str) or not script[key].strip() or len(script[key]) > 1200:
			raise ValueError("Script requires concise " + key + ".")
	for key in ("visual_style", "music"):
		# Both feed model prompts (pictures, music) and must be English.
		if VIETNAMESE.search(script[key]):
			raise ValueError(f"Write {key} in English; it is a production prompt, not viewer text.")
	if STYLE_SUBJECT.search(script["visual_style"]):
		raise ValueError(
			"visual_style is art direction only (rendering, lighting, palette, material, mood); remove the subjects it names, such as "
			+ ", ".join(sorted({m.lower() for m in STYLE_SUBJECT.findall(script["visual_style"])}))
			+ "."
		)
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
	for scene_index, scene in enumerate(script["scenes"]):
		if not isinstance(scene, dict):
			raise ValueError("Each scene must be an object.")
		duration = scene.get("duration_seconds")
		if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 30:
			raise ValueError("Scene duration must be finite, positive and at most thirty seconds.")
		total += duration
		for field in ("beat_name", "visual_camera", "action", "visible_change", "place", "continuity_rules"):
			if not isinstance(scene.get(field), str) or not scene[field].strip() or len(scene[field]) > 2400:
				raise ValueError("Every scene requires " + field + ".")
		# Everything is English except what viewers see or hear (voice-over,
		# on-screen text and CTA), which uses the viewers' language.
		viewer = VIEWER_FIELDS
		english = constraints.get("language", "English") == "English"
		# Before translation, on-screen text may already be in the viewers' language.
		checked_viewer = (
			viewer if english and constraints.get("viewer_language", "English") == "English" else ()
		)
		for field in (
			"beat_name",
			"visual_camera",
			"action",
			"visible_change",
			"place",
			*checked_viewer,
		):
			if _foreign(scene.get(field)):
				raise ValueError(f"Scene {scene_index + 1} {field} must be written in English.")
		if not english:
			for field in viewer:
				if len(ENGLISH_WORDS.findall(scene.get(field) or "")) >= 2:
					raise ValueError(
						f"Scene {scene_index + 1} {field} must be written in {constraints['language']}, the viewers' language."
					)
		flexible = any(
			item["role"] == "Product"
			and any(
				"construction: flexible" in str(view.get("description") or "").lower()
				for view in item.get("views") or []
			)
			and any(
				reference_options.get(key, {}).get("identity") == (item.get("identity") or item["key"])
				for key in scene.get("products") or []
			)
			for item in inventory
		)
		wrong = (
			sorted(
				{
					m.lower()
					for field in ("visual_camera", "action", "visible_change")
					for m in RIGID_CONTAINER.findall(scene.get(field) or "")
				}
			)
			if flexible
			else []
		)
		if wrong:
			raise ValueError(
				f"Scene {scene_index + 1} treats the flexible pack as a rigid container ({', '.join(wrong)}); call it a pack and use only its real opening, without invented lids, films or seals."
			)
		if STATE_RESET.search(scene["action"]):
			raise ValueError(
				f"Scene {scene_index + 1} puts used material back into its container; used items stay out (set aside or discarded) and the story moves forward."
			)
		if EDITORIAL_TEXT.search(scene["action"]):
			raise ValueError(
				f"Scene {scene_index + 1} puts editing text in action; write it in on_screen_text and give the scene a visible action or a stable product view."
			)
		named = sorted(
			key
			for key in reference_options
			if re.search(r"[_\d]", key)
			and any(
				re.search(rf"(?<![\w]){re.escape(key)}(?![\w])", scene.get(field) or "", re.I)
				for field in ("visual_camera", "action", "visible_change", "continuity_rules", "voice_over")
			)
		)
		if named:
			raise ValueError(
				f"Scene {scene_index + 1} names subjects by reference keys ({', '.join(named)}); keys belong only in cast/products. Describe them visually in prose, for example 'the bear mascot' or 'the tissue pack'."
			)
		if MONTAGE.search(scene["action"]):
			raise ValueError(
				f"Scene {scene_index + 1} packs a montage into one shot; give each place or situation its own scene, or keep one continuous action."
			)
		scene["action"] = normalize_action_separators(scene["action"])
		phases = read_timed_actions(scene["action"], duration)
		if phases is None:
			raise ValueError(
				"Use explicit chronological timed action phases for a visible subject/product event. "
				"A camera move belongs in camera direction and cannot replace the shot's physical action."
			)
		from joymedia.services.planning.camera import without_camera

		cleaned = [without_camera(phase["action"]).strip() for phase in phases]
		if any(clean != phase["action"].strip() for clean, phase in zip(cleaned, phases, strict=True)):
			if not all(cleaned):
				raise ValueError(
					"Move camera movement out of Action and into camera direction. Replace a camera-only "
					"phase with the supplied subject visibly completing a product interaction; do not "
					"merely delete camera words and leave the product static."
				)
			scene["action"] = "\n".join(
				f'[{phase["start"]:g}-{phase["end"]:g}s] {clean}'
				for phase, clean in zip(phases, cleaned, strict=True)
			)
			phases = read_timed_actions(scene["action"], duration)
		if (
			"action_reference_observations" in constraints
			and not constraints["action_reference_observations"]
			and not constraints.get("client_examples")
			and UNANCHORED_PHYSICAL_EFFECT.search(scene["action"])
		):
			heuristic(
				"A cleaning, fluid or material-stress effect needs a supplied action reference; choose a directly visible product-handling action instead."
			)
		stranger = None
		if not any(item["role"] == "Person" for item in inventory):
			stranger = ANONYMOUS_HUMAN.search(
				scene["action"] + "\n" + (scene.get("visual_camera") or "")
			) or (not scene.get("cast") and BODY_PART.search(scene["action"]))
		if stranger:
			raise ValueError(
				f'Scene {scene_index + 1}: an anonymous human limb or actor ("{stranger.group(0)}") is not among the supplied references; cast a supplied character to perform the action, or show the product alone.'
			)
		if {_plain(scene.get("voice_over")), _plain(scene.get("on_screen_text"))} & set(
			constraints.get("example_voice_lines") or []
		):
			raise ValueError(
				f"Scene {scene_index + 1} copies an example script's voice-over or on-screen text; write new lines for this product."
			)
		if (
			scene_index < 2
			and PASSIVE_OPENING.search(scene["action"])
			and not TANGIBLE_ACTION.search(scene["action"])
		):
			heuristic(
				"The opening cannot consist only of looking, posing or holding; start with a visible object action or material state change."
			)
		for key, choices in (("shot_framing", FRAMINGS), ("shot_angle", ANGLES), ("narrative_stage", STAGES)):
			if scene.get(key) not in choices:
				raise ValueError("Unsupported " + key + ".")
		if "camera_move" in scene and scene["camera_move"] not in CAMERA_MOVES:
			raise ValueError("Unsupported camera_move.")
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
	try:
		_validate_action_progress(script["scenes"])
	except ValueError as exc:
		heuristic(str(exc))
	closing = script["scenes"][-1]
	if closing.get("products") and closing.get("cast") and not TANGIBLE_ACTION.search(closing.get("action") or ""):
		raise ValueError(
			"A static closing product packshot must not add an inactive actor. "
			"Keep the final hero product on its real support with cast empty, or give the supplied actor "
			"one meaningful completed product action in that shot."
		)
	conflict = _later_acquisition_conflict(script["scenes"])
	if conflict:
		earlier, later, item = conflict
		raise ValueError(
			f"Scene {earlier} uses the {item} before scene {later} obtains it from its source. "
			"Reorder the action or explicitly establish a different already-available item."
		)
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
	if not script["scenes"][-1]["products"]:
		raise ValueError("End on the product: the final scene must show the supplied product with its CTA.")
	for index, scene in enumerate(script["scenes"], 1):
		rules, action = scene.get("continuity_rules") or "", scene["action"]
		stay, move = STAY_RULE.search(rules), LOCOMOTION.search(action)

		def actor(text, match):
			# The words just before the verb name who stays or moves ("Bear remains", "the bear walks").
			return {w for w in re.findall(r"[a-z]{4,}", text[: match.start()].lower().split(".")[-1])[-3:]}

		if stay and move and actor(rules, stay) & actor(action, move):
			raise ValueError(
				f'Scene {index}: the continuity rule "{stay.group(0)}" contradicts the action "{move.group(0)}"; make the rule and the action agree.'
			)
	happened = False
	for index, scene in enumerate(script["scenes"], 1):
		for phase in read_timed_actions(scene["action"]) or [{"action": scene["action"]}]:
			if MESS.search(phase["action"]) and not happened and not MESS_EVENT.search(phase["action"]):
				raise ValueError(
					f'Scene {index} cleans a mess that never happened on camera ("{MESS.search(phase["action"]).group(0)}"); show it being made in an earlier action phase or scene first.'
				)
			happened = happened or bool(MESS_EVENT.search(phase["action"]))
	for index, scene in enumerate(script["scenes"][:-1], 1):
		if CLOSING_BEAT.search(scene.get("beat_name") or ""):
			raise ValueError(
				f"Scene {index} is the packshot/CTA but the film continues after it. "
				f"Replace scene {index}'s beat name, on-screen text and action with a distinct "
				f"product-use or detail beat; move its CTA text to final scene {len(script['scenes'])}. "
				"The final scene alone must be named packshot/CTA and finish on the supplied product."
			)
	if len(script["scenes"]) > 2 and script["scenes"][-1]["duration_seconds"] > max(6.0, 0.2 * total):
		raise ValueError(
			f"The closing scene lasts {script['scenes'][-1]['duration_seconds']:g}s; keep the final presentation brief (at most {max(6.0, 0.2 * total):g}s) and give the time to product actions."
		)
	cast = {key for scene in script["scenes"] for key in scene["cast"]}
	for item in inventory:
		if item["role"] in {"Character", "Person"} and not any(
			v.get("key", item["key"]) in cast for v in item.get("views") or [{"key": item["key"]}]
		):
			raise ValueError(
				f"The supplied character {item['key']} never appears; make it the protagonist who performs the product actions."
			)
	return script


def script_workbook(script, project, lang="en", pictures=None):
	"""Fill the existing downloadable template; its importer remains authoritative.

	pictures: {scene number: image path}, each scene's drawn first frame; placed in a
	column after the template's, which the importer ignores.
	"""
	from openpyxl import load_workbook

	from joymedia.services.intake.references import brand, preservation_modes
	from joymedia.services.intake.template import BRIEF_ROWS, HEADER_ROW, SHEET_TITLES, build_template
	from joymedia.services.planning.workbook import (
		BRAND_FIELDS,
		REFERENCE_COLUMNS,
		REFERENCE_TYPE_LABELS,
		SCENE_COLUMNS,
	)
	from joymedia.services.scene.references import canonical_reference_rows

	# AI-written workbooks use the English template so planning reads them without
	# translation; only an imported client workbook in another language is translated.
	book = load_workbook(io.BytesIO(build_template(lang)))
	sheet = book[SHEET_TITLES["sheet"][lang]]
	# Remove every example value, preserving schema headers and styling.
	for row in sheet.iter_rows(min_row=1, max_row=HEADER_ROW - 1, min_col=2, max_col=2):
		for cell in row:
			cell.value = None
	for row in sheet.iter_rows(min_row=HEADER_ROW + 1):
		for cell in row:
			cell.value = None
	metadata = {
		"product_name": project.product_name or script.get("product_name") or script["title"],
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
	if pictures:
		_place_frames(sheet, HEADER_ROW, len(SCENE_COLUMNS) + 2, pictures, lang)
	refs = book[SHEET_TITLES["references"][lang]]
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
			"type": REFERENCE_TYPE_LABELS.get(row.reference_role, {}).get(lang, row.reference_role),
			"file": frappe.get_doc("File", {"file_url": asset.file}).file_name,
			"keep_rule": row.keep_rule or "",
			"preservation_mode": modes.get(row.asset_version, ""),
			"description": analysis.get("description", "") if row.reference_role == "Environment" else "",
		}
		for col, key in enumerate(REFERENCE_COLUMNS, 1):
			refs.cell(i, col, values.get(key, ""))
	bs = book[SHEET_TITLES["brand"][lang]]
	bs.delete_rows(1, bs.max_row)
	authored = brand(project)
	cta = next((s["on_screen_text"] for s in reversed(script["scenes"]) if s.get("on_screen_text")), "")
	values = {
		"key_message": script.get("key_message", ""),
		"audience": script.get("audience", ""),
		"avoid": "Use only the approved claims; no other products, characters or people.",
		"mandatories": "\n".join(
			filter(
				None,
				[
					f"Logo {script.get('product_name') or project.product_name or ''}".strip(),
					cta and "CTA: " + cta,
				],
			)
		),
		**{k: v for k, v in authored.items() if v},
		**({"claims": script["claims"]} if script.get("claims") and not authored.get("claims") else {}),
		"logline": script["logline"],
		"visual_style": script["visual_style"],
		"camera_style": "cinematic",
	}
	for i, (key, spec) in enumerate(BRAND_FIELDS.items(), 1):
		value = values.get(key, "")
		bs.cell(i, 1, spec["label"][lang])
		bs.cell(i, 2, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
	buffer = io.BytesIO()
	book.save(buffer)
	return buffer.getvalue()
