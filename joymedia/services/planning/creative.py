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

from joymedia.services.audio.direction import voiceover_writer_rules
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
	"Write the story for canonical character identities, never for a photographed pose or an alternate reference view. "
	"A separate object a character holds in its reference photo (a toy, a heart, a cup) belongs to that photo, not to the character: show it only where the story uses it. "
	"Describe the physically supported body state and action the story needs; a later pose-preparation stage reads this completed script, then selects or generates the opening Character view for each scene. "
	"Do not change, limit or simplify an action merely because the supplied identity photograph shows a different pose. Change body state where the story gains from it, not in every scene. "
	"For a multi-scene character commercial, do not keep the actor in the source photograph's pose for every action by default. Plan a visible, physically supported change of body state or orientation when it advances the story; name that change in the timed action and maintain its support across subsequent shots. A different camera crop of the same seated body is not an action or pose change. "
	"Keep one coherent interaction per shot, chronological prerequisites and persistent object/support states. "
	"Before each grasp, put the actor and target within a natural paw or hand reach in the opening visual_camera; state their support and relative position there, before the timed action starts. If the original body position cannot reach, establish a visible move first or choose a different interaction. Check that a paw is free. These checks are for you: the timed action states only what visibly happens, never an assurance that a rule is met (that a paw is free, a pose is possible or something is positioned correctly).An actor carrying two objects must explicitly set one down before taking a third. Track each object's supporting surface between shots; show any transfer rather than silently moving it. Keep furniture load bearing, with a fully visible ordinary table supported by four connected floor-contacting legs. "
	"Fit each support to the character's build and size in its reference photos: a large or round-bodied figure sits on the floor, a rug, a sofa or a bench, or stands beside low furniture, rather than perching on an ordinary chair or squeezing under or behind a tabletop it cannot fit. "
	"Tell a story a viewer wants to finish: a surprising or relatable hook in the first seconds, a small everyday problem, the product as the turning point with a visible cause and result, an emotional payoff, then the brand. Every scene adds something new; never show the same demonstration twice. "
	"Give the film rhythm: scene durations are relative weights, so make the hook quick, give the key proof the most time, keep detail cutaways and the closing brand shot short. Never put more than two close handling details in a row; follow them with a reaction, a visible result or a wider shot. "
	"Direct the camera with intent: the opening moves (an arc or push-in), a precise contact detail holds still, a reaction pushes in, the finale pulls back; mix wide, medium, close and detail sizes, and use low, high or overhead angles where they serve the moment. "
	"When a product-bearing opening benefits from a different package orientation, name that orientation in the shot script separately from the room camera. Product-view preparation follows the completed script; available pictures must not dictate the story or imply that hidden printing is verified. "
	"Invent no opening mechanism. Extracted consumables remain outside their unused stock; do not reset the story by putting them back. "
	"Do not invent a performance test or effect that the approved claims do not support; visible material handling is enough. "
	"Name every ordinary prop and action target before use. Non-final shots advance tangible object/action state, not prolonged looking or posing. "
	"A real change of material form, object location or contact is tangible progress. The final branded presentation may hold briefly. "
	"Use purposeful coverage and action-driven phase timings, with camera behavior derived from semantic structure. "
	"Give the shared location believable depth, material texture and motivated practical light; name the subject's real support and keep it visible in broad shots. Do not default to an empty minimalist backdrop unless the supplied environment or brief asks for one. Keep the same architecture and lighting across connected shots while varying shot size and angle. "
	"When the cast is an illustrated character, every visible hand, arm, finger or paw belongs to that cast; never introduce a real human hand, arm or person."
)

UNANCHORED_PHYSICAL_EFFECT = re.compile(
	r"\b(?:water|liquid|spill|stain|dust|dirt|grime|clean|polish|soak|absorb|wet|dip|pour|rinse|tear|stretch|break)\w*\b",
	re.I,
)
AUTHORED_PHYSICAL_EFFECT = re.compile(
	r"(?:\b(?:water|liquid|spill|stain|dust|dirt|clean|soak|absorb|absorp|wet|pour|tear|stretch)\w*\b|nước|vết bẩn|thấm|đổ|tràn|lau|rách|kéo giãn)",
	re.I,
)
# The style is appended to every picture prompt, including empty-place drawings:
# naming subjects there puts extra characters or products into the set.
STYLE_SUBJECT = re.compile(
	r"\b(?:mascots?|characters?|people|persons?|humans?|animals?|toys?|products?|packag\w*|packs?|logos?)\b",
	re.I,
)
# The AI writer chooses lighting and palette, never a flat medium: the client's photos fix the medium.
FLAT_MEDIUM = re.compile(
	r"\b(?:2d|cartoon\w*|animat\w*|anime|illustrat\w*|hand[- ]drawn|watercolou?r|paint\w*|sketch\w*|comic\w*|"
	r"clay\w*|pixel\w*|cel[- ]shaded)\b",
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
	r"\b(?:spills|spilled|spilling|spill(?:s)?\s+(?:over|out)|tips?\s+over|knocks?\s+over|drops?|falls?|falling|splash(?:es|ed)|drips|dripping|smears|leaks|overflows?)\b",
	re.I,
)
WET_EVENT = re.compile(
	r"\b(?:spills|spilled|spilling|splashes|splashed|splashing|drips|dripped|dripping|"
	r"pours|poured|pouring|leaks|leaked|leaking|overflows|overflowed|overflowing|"
	r"tips?\s+over|knocks?\s+over)\b"
	r"|\b(?:water|liquid|droplets?)\b[^.;\n]{0,60}\b(?:drop|drops|fall|falls|falling|land|lands)\b",
	re.I,
)
# A clean-up can be described without the nouns above ("wipe a wet surface").
# It still needs a visible cause in an earlier phase or shot.
WET_CLEANUP = re.compile(
	r"\b(?:wipe|wipes|wiping|dab|dabs|blot|blots|dry|dries|absorb|absorbs|clean|cleans)\b"
	r"[^.;\n]{0,90}\b(?:wet|water|liquid|moist|damp)\b",
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
	r"\b(?:pick|place|set|lift|grip|grab|grasp|pull|extract|unfold|fold|wipe|rub|dab|pat|blot|touch|apply|absorb|carry|turn|open|slide|tap|press|unwrap|wear|put|move|push|drop|rotate|spill|pour|tip|knock|scatter|spread|splash)\w*\b",
	re.I,
)
ACQUIRED_OBJECT = re.compile(
	r"\b(?:picks?\s+up|lifts?|grabs?|takes?)\s+(?:the|an?|this)\s+([a-z][a-z -]{1,65}?)(?=\s+(?:and|to|from|off|onto|on|with)\b|[.,;\n]|$)",
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
	"""Require a completed object interaction in each non-closing action shot."""
	for index, scene in enumerate(scenes[:-1]):
		if index:
			prior = scenes[index - 1]["action"]
			current = scene["action"]
			prior_targets = {match.group(1).strip().casefold() for match in ACQUIRED_OBJECT.finditer(prior)}
			current_targets = {
				match.group(1).strip().casefold() for match in ACQUIRED_OBJECT.finditer(current)
			}
			if prior_targets & current_targets and not re.search(
				r"\b(?:places?|puts?|sets?|releases?)\b", prior, re.I
			):
				raise ValueError(
					f"Scene {index + 1} acquires the same object again without placing it after scene {index}. "
					"Continue from the retained grip, or show the placement before a new acquisition."
				)
		if (
			index == len(scenes) - 2
			and scene.get("products")
			and scene.get("shot_framing") in {"close_up", "extreme_close_up"}
		):
			continue
		phases = read_timed_actions(scene["action"], scene["duration_seconds"])
		# Set dressing in a relative clause is not an action.
		if not any(
			TANGIBLE_ACTION.search(
				re.sub(
					r"\bturns?\s+to\s+look\b|\bmoves?\s+(?:to|toward)\s+look\b",
					"",
					re.split(r"\b(?:where|which|that)\b", phase["action"], maxsplit=1, flags=re.I)[0],
					flags=re.I,
				)
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


def _validate_product_support_continuity(scenes):
	"""A carried package cannot reappear on furniture without a visible placement."""
	package = r"(?:pack|packet|package|box)"
	pick_up = re.compile(
		rf"\b(?:picks?\s+up|lifts?|grabs?|grasps?|takes?)\s+(?:the|a|an)?\s*(?:tissue\s+)?{package}\b",
		re.I,
	)
	put_down = re.compile(
		rf"\b(?:places?|puts?|sets?|returns?|lowers?)\s+(?:the|a|an)?\s*(?:tissue\s+)?{package}\b",
		re.I,
	)
	on_support = re.compile(
		rf"\b{package}\b[^.\n]{{0,55}}\b(?:on|atop)\s+(?:the|a)?\s*(?:coffee\s+)?(?:table|counter|shelf)\b",
		re.I,
	)
	carried_since = None
	for index, scene in enumerate(scenes, 1):
		opening = str(scene.get("visual_camera") or "")
		if carried_since and on_support.search(opening):
			raise ValueError(
				f"Scene {index} shows the package on furniture after scene {carried_since} picked it up "
				"without a visible placement. Add a timed placement action before this shot."
			)
		action = str(scene.get("action") or "")
		for _, event in sorted(
			[(m.start(), "pick") for m in pick_up.finditer(action)]
			+ [(m.start(), "place") for m in put_down.finditer(action)]
			+ [(m.start(), "support") for m in on_support.finditer(action)]
		):
			if event == "support" and carried_since:
				raise ValueError(
					f"Scene {index} says the carried package is on furniture without showing its placement."
				)
			if event == "pick":
				carried_since = index
			elif event == "place":
				carried_since = None


def _validate_character_support_continuity(scenes, reference_options):
	"""Require a visible transition before an actor changes support across cuts."""
	from joymedia.services.planning.pose_coverage import SEATED, STAND_UP, UPRIGHT

	sit_down = re.compile(
		r"\b(?:sit(?:s|ting)?\s+down|takes?\s+(?:a\s+)?seat|settles?\s+into\s+(?:a\s+)?seat)\b", re.I
	)
	last = {}
	for number, scene in enumerate(scenes, 1):
		opening = str(scene.get("visual_camera") or "")
		state = "seated" if SEATED.search(opening) else ("upright" if UPRIGHT.search(opening) else None)
		action = str(scene.get("action") or "")
		for cast_key in scene.get("cast") or []:
			identity = (reference_options.get(cast_key) or {}).get("identity") or cast_key
			previous = last.get(identity)
			if state and previous and state != previous:
				raise ValueError(
					f"Scene {number} opens with character {identity} {state} after a {previous} "
					"scene without a visible stand-up or sit-down transition."
				)
			if state:
				last[identity] = state
			if STAND_UP.search(action):
				last[identity] = "upright"
			elif sit_down.search(action):
				last[identity] = "seated"


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


def marketing_job(scene, position, total):
	"""Describe an example scene's commercial function without exposing its plot.

	Client examples can teach advertising rhythm, but their actors, props and
	actions must never leak into a newly generated screenplay.  These tags are
	therefore intentionally small, generic production roles.
	"""
	if position == 0:
		return "action_hook"
	if position == total - 1:
		return "hero_cta"
	text = " ".join(str(scene.get(key) or "") for key in ("beat_name", "action", "visible_change")).casefold()
	if re.search(
		r"\b(?:spill|mess|problem|panic|worry|dirty|fail|tear|break)\w*\b|đổ|bẩn|hoảng|rối",
		text,
	):
		return "tension"
	if re.search(
		r"\b(?:pull|extract|open|unbox|reveal|take out|introduce)\w*\b|rút|mở|xuất hiện|lấy ra",
		text,
	):
		return "product_response"
	if re.search(
		r"\b(?:absorb|clean|wipe|dry|stretch|thick|soft|proof|test|demonstrat)\w*\b|thấm|lau|dai|mềm|dày|chứng minh",
		text,
	):
		return "tactile_proof"
	if re.search(
		r"\b(?:smile|laugh|hug|comfort|relief|enjoy|use|lifestyle)\w*\b|cười|ôm|nhẹ nhõm|an tâm|thoải mái",
		text,
	):
		return "payoff"
	return "product_action"


def commercial_action_findings(scenes, total_seconds):
	"""Return repairable findings for a flat long-form commercial arc.

	This is a marketing-rhythm check, not a claim checker: it requires a visible
	cause-and-effect progression while leaving the product-specific action to the
	references, approved claims and physical-action rules.
	"""
	if total_seconds < 20 or len(scenes) < 4:
		return []
	findings = []
	active = scenes[:-1]
	if len(scenes) >= 3 and not scenes[-1].get("cast") and not scenes[-2].get("cast"):
		last_actions = [_plain(re.sub(r"\[[^]]+\]", "", scene.get("action") or "")) for scene in scenes[-2:]]
		if last_actions[0] and last_actions[0] == last_actions[1]:
			findings.append(
				"The last two scenes repeat the same static product presentation. Give the penultimate scene a distinct product detail or completed interaction, then reserve the last scene for the hero CTA."
			)
	# Repeating the same physical verb in separate beats usually creates a
	# product demo that stalls (for example, a second rubbing/pressing beat).
	# Keep this advisory so an explicitly authored repetition can be reviewed.
	physical_verbs = re.compile(
		r"\b(?:rub|press|fold|unfold|wipe|dab|blot|tap|squeeze|stretch|tear|pull|extract|open|close|place|lift|carry|grip|grasp)\w*\b",
		re.I,
	)
	verb_scenes = {}
	for index, scene in enumerate(active, 1):
		for verb in {
			match.group(0).lower().rstrip("s") for match in physical_verbs.finditer(scene.get("action") or "")
		}:
			verb_scenes.setdefault(verb, []).append(index)
	for verb, indexes in verb_scenes.items():
		if len(indexes) >= 2:
			findings.append(
				f"Scenes {', '.join(map(str, indexes))} repeat the same '{verb}' demonstration. "
				"Give each scene a distinct physical result or combine the repeated handling into one shot."
			)
			break
	phase_counts = [
		len(read_timed_actions(scene.get("action"), scene.get("duration_seconds")) or []) for scene in active
	]
	if not any(count >= 2 for count in phase_counts):
		findings.append(
			"The commercial has only one-step demonstrations. Give one supported product beat two causal phases (setup/contact, then visible result) so the benefit feels earned."
		)
	stages = [scene.get("narrative_stage") for scene in active]
	if any(stages[index] == stages[index - 1] == stages[index - 2] for index in range(2, len(stages))):
		findings.append(
			"Three adjacent scenes have the same narrative job. Replace the repeated handling with a distinct response, proof, payoff or presentation beat."
		)
	story_stages = {"extract", "unfold", "inspect", "detail", "feel", "present"}
	if len(set(stages) & story_stages) < 3:
		findings.append(
			"The middle of this commercial lacks enough distinct product-story beats. Progress from response to tactile proof to a visible payoff instead of repeating the same handling gesture."
		)
	if not any(stage in {"feel", "present"} for stage in stages):
		findings.append(
			"Show a brief supported payoff after the proof: a character's reaction or a clear product presentation caused by the completed action."
		)
	return findings


def script_exemplars(file_names, index=0, *, scene_chars=520):
	"""Client workbooks or reviewed fallback examples -> compact writer guidance.

	Examples teach structure, pacing, tone and how the client writes voice-over and
	on-screen text. The writer gets a new premise; their selling points are client
	claims. The primary example rotates with the variant so variants differ.
	"""
	from joymedia.services.planning.workbook import parse_storyboard_workbook

	if not file_names:
		return approved_script_exemplars(index)

	def shot_sizes(value):
		text = str(value or "").casefold()
		patterns = (
			("extreme_close_up", r"extreme close[- ]?up|macro|siêu cận"),
			("close_up", r"close[- ]?up|cận cảnh"),
			("medium", r"medium shot|trung cảnh"),
			("wide", r"wide shot|toàn cảnh"),
			("top_down", r"top[- ]?down|từ trên xuống"),
		)
		return [name for name, pattern in patterns if re.search(pattern, text)]

	examples, claims, formats, voice_lines, screen_lines = [], [], set(), [], []
	for name in file_names or []:
		path = frappe.get_doc("File", name).get_full_path()
		for demo in parse_storyboard_workbook(path)["demos"]:
			if not demo.get("scenes"):
				continue
			for scene in demo["scenes"]:
				for field in ("voice_over", "on_screen_text"):
					line = _plain(scene.get(field))
					if len(line) > 8:
						voice_lines.append(line)
				if scene.get("on_screen_text"):
					screen_lines.append(scene["on_screen_text"])
			meta = demo.get("metadata") or {}
			formats.add(_ratio_text(meta.get("format")))
			claims.extend(
				line.strip(" -•") for line in str(meta.get("usp") or "").splitlines() if line.strip(" -•")
			)

			def clip(value, limit):
				value = " ".join(str(value or "").split())
				return value if len(value) <= limit else value[: limit - 1] + "…"

			example_seconds = sum(float(s.get("duration_seconds") or 0) for s in demo["scenes"])

			examples.append(
				{
					"tone": clip(meta.get("tone_mood"), 120),
					"marketing_rhythm": [
						marketing_job(scene, scene_index, len(demo["scenes"]))
						for scene_index, scene in enumerate(demo["scenes"][:8])
					],
					"scenes": [
						{
							"sequence": scene_index + 1,
							"duration_share": round(
								float(s.get("duration_seconds") or 0) / example_seconds, 2
							)
							if example_seconds
							else 0,
							"shot_sizes": shot_sizes(s.get("visual_camera")),
							"voice_words": len(str(s.get("voice_over") or "").split()),
							"screen_words": len(str(s.get("on_screen_text") or "").split()),
						}
						for scene_index, s in enumerate(demo["scenes"][:8])
					],
				}
			)
	if not examples:
		return {}
	start = index % len(examples)
	ordered = examples[start:] + examples[:start]
	return {
		"screen_lines": screen_lines,
		"language": "Vietnamese" if len(VIETNAMESE.findall(" ".join(voice_lines))) > 20 else "English",
		# The client's authored format, when every example states the same one.
		"format": next(iter(formats)) if len(formats) == 1 and all(formats) else None,
		"voice_lines": voice_lines,
		"marketing_rhythm": ordered[0].get("marketing_rhythm", []),
		# Pass only timing, framing and line lengths to the writer; source plot and
		# wording remain private for copy detection and translation style.
		"examples": [ordered[0]] + [{"scenes": e["scenes"]} for e in ordered[1:3]],
		"claims": list(dict.fromkeys(claims))[:12],
	}


def approved_script_exemplars(index=0):
	"""Use reviewed, anonymized pacing examples when no client workbook is supplied.

	The data file contains only shot sizes, relative timing and line lengths. It
	never gives another project's subject, claims, dialogue or plot to the writer.
	"""
	from pathlib import Path

	path = Path(__file__).with_name("approved_examples.json")
	try:
		stored = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return {}
	examples = [
		{key: example[key] for key in ("tone", "marketing_rhythm", "scenes") if key in example}
		for example in stored.get("examples", [])
		if isinstance(example, dict) and isinstance(example.get("scenes"), list)
	]
	if not examples:
		return {}
	ordered = examples[index % len(examples) :] + examples[: index % len(examples)]
	return {
		"examples": [ordered[0]] + [{"scenes": row["scenes"]} for row in ordered[1:3]],
		"marketing_rhythm": ordered[0].get("marketing_rhythm", []),
		"claims": [],
		"voice_lines": [],
		"screen_lines": [],
	}


class ReferenceAnalysisUnavailable(ValueError):
	"""An image analysis attempt failed and can be retried without changing the script."""


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
				message = "Product/mascot reference analysis is missing: " + view.reference_key
				if asset.analysis_status == "Failed":
					raise ReferenceAnalysisUnavailable(message)
				raise ValueError(message)
			from joymedia.services.planning.pose_assets import _qualified_pose_metadata

			qualified = _qualified_pose_metadata(analysis)
			qualified_pose = (qualified or {}).get("pose") or ""
			qualified_view = (qualified or {}).get("view") or ""
			views.append(
				{
					"key": view.reference_key,
					"product_view": view.get("product_view") if view.reference_role == "Product" else "",
					"pose_and_support": qualified_pose
					or (
						"" if analysis.get("source_asset_version") else analysis.get("pose_and_support") or ""
					),
					"qualified_pose": qualified_pose,
					"qualified_view": qualified_view,
					"description": " ".join(
						filter(
							None,
							[
								analysis.get("description", ""),
								("Qualified reusable pose/support: " + qualified_pose)
								if qualified_pose
								else ("Visible pose/support: " + analysis["pose_and_support"])
								if analysis.get("pose_and_support")
								and not analysis.get("source_asset_version")
								else "",
								("View constraint: " + view.keep_rule) if view.keep_rule else "",
								("Declared package view: " + view.get("product_view"))
								if view.reference_role == "Product"
								and view.get("product_view")
								and view.get("product_view") != "source"
								else "",
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
	"""Expose canonical identities to the Director, never pose-view implementation keys.

	The screenplay is the source of required poses.  Alternate Character images
	are intentionally absent here so that their current posture cannot steer the
	story.  ``prepare_script_pose_views`` resolves each scripted opening state
	after this validation step and replaces the cast with a concrete view only
	for storyboard and frame generation.
	"""
	return {
		item["key"]: {"role": item["role"], "identity": item.get("identity") or item["key"]}
		for item in inventory
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
	scene["product_view"] = {
		"type": "string",
		"enum": [
			"source",
			"front",
			"front_left",
			"front_right",
			"top_front",
			"three_quarter",
			"side",
			"left",
			"right",
			"back",
		],
		"description": "Opening angle of the visible hero product, separate from the room camera. Use source when no different package orientation is required or the product is absent. Specify a different angle only when the opening frame needs it; unseen print remains unverified.",
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
	scene["opening_support"] = {
		"type": "string",
		"enum": ["standing", "seated", "lying", "none"],
		"description": "How the cast's body is supported in the opening frame, before the first timed action: standing, seated or lying. Use none only when no character is cast. Keep it consistent with the previous scene unless that scene shows the change.",
	}
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
				/ (constraints["max_scene_frames"] * PACING_HEADROOM)
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
	if max_scene_frames and len(weights) * max_scene_frames < round(total * fps):
		required = math.ceil(round(total * fps) / max_scene_frames)
		raise ValueError(
			f"A {total:g}-second video at {fps:g} fps needs at least {required} scenes "
			f"with this workflow's {max_scene_frames}-frame shot capacity; received {len(weights)}. "
			"Add distinct, chronological action beats instead of lengthening existing shots."
		)
	if len(weights) > 2 and len(set(weights)) == 1:
		weights = [
			JOB_WEIGHTS.get(scene.get("narrative_stage"), 1.0) * (1 + 0.12 * (len(phases) - 1))
			for scene, phases in zip(script["scenes"], actions, strict=True)
		]
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


def _freeze_proposed_duration(constraints, schema, proposal):
	"""Fit Auto duration to the proposed distinct scenes and workflow capacity."""
	if constraints.get("duration_seconds") is not None:
		return
	seconds = proposal.get("duration_seconds") if isinstance(proposal, dict) else None
	if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 60:
		return
	capacity = constraints.get("max_scene_frames")
	scenes = proposal.get("scenes") if isinstance(proposal, dict) else None
	if capacity and isinstance(scenes, list) and 2 <= len(scenes) <= 12:
		# The user chose Auto. A proposed four-beat story should be shortened to
		# four renderable shots, rather than padded with two invented idle beats.
		seconds = (
			min(round(seconds * constraints["fps"]), math.floor(len(scenes) * capacity * PACING_HEADROOM))
			/ constraints["fps"]
		)
	constraints["duration_seconds"] = seconds
	schema["properties"]["duration_seconds"] = {"const": seconds}
	if capacity:
		minimum = max(2, math.ceil(round(seconds * constraints["fps"]) / (capacity * PACING_HEADROOM)))
		if minimum > schema["properties"]["scenes"]["maxItems"]:
			raise ValueError(
				"The proposed duration exceeds this workflow's automatic storyboard scene budget."
			)
		schema["properties"]["scenes"]["minItems"] = minimum


def unique_scene_names(script):
	"""Give AI-written scenes stable unique keys for storyboard and graphics joins."""
	seen = set()
	for scene in script.get("scenes") or []:
		name = " ".join(str(scene.get("beat_name") or "").split())
		candidate = name
		number = 2
		while candidate.casefold() in seen:
			suffix = f" ({number})"
			candidate = name[: 100 - len(suffix)] + suffix
			number += 1
		scene["beat_name"] = candidate
		seen.add(candidate.casefold())
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

	# The Director sees canonical identities only.  It writes the required body
	# states into the screenplay; pose preparation runs after script validation.
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
		# Abstract roles only: examples teach commercial momentum, never their
		# products, story actions, actors or wording.
		"example_marketing_rhythm": list(examples.get("marketing_rhythm") or [])[:8],
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
			# Only the canonical identity description reaches the Director.  Pose
			# variants remain available to the following pose-preparation stage,
			# but their visible support must not determine this story.
			"identity_reference": (item.get("views") or [{}])[0].get("description", "")[:320],
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
	authored_effect = bool(
		AUTHORED_PHYSICAL_EFFECT.search(
			" ".join((constraints.get("mandatories") or "", constraints.get("creative_direction") or ""))
		)
	)
	effect_rule = (
		"A physical effect explicitly requested in the creative direction or brand mandatories may be shown without an action video: stage its visible cause in a distinct earlier action phase or shot, then contact, then a gradual visible result. Do not add other effects or claim an instant result. "
		if authored_effect
		else "Liquids, spills, crumbs, stains, cleaning, tearing and stretching appear only when a supplied action observation supports them. Otherwise show direct handling and product detail. "
	)
	prompt = (
		"Write an ORIGINAL product commercial screenplay. "
		+ (
			"Follow the CLIENT EXAMPLE SCRIPTS for structure, pacing, tone, voice-over and on-screen text style (action hook, product response, visible proof, payoff, packshot with CTA), but invent a new premise; never copy their story, products or cast. A problem beat is optional and must be supported by the supplied action references. "
			if examples.get("examples")
			else "Use a commercial structure: action hook, product response, visible proof, payoff, packshot with CTA. A problem beat is optional and must be supported by the supplied action references. "
		)
		+ "Write every field in English (examples may be in another language; never copy their wording). "
		+ (
			f"voice_over and on_screen_text (including the CTA) will be translated into {viewer_language} for the viewers: keep them short. "
			if viewer_language != "English"
			else ""
		)
		+ SHOT_GUIDE
		+ " "
		+ voiceover_writer_rules()
		+ " "
		+ "MARKETING ACTION ARC: For a commercial of twenty seconds or more, build a visible progression: an immediate action hook; a product response that changes the situation; a tactile or functional proof caused by that response; a brief payoff (reaction or presentation); then a clean hero CTA. A tension/problem is optional and only allowed when the supplied action references make it physically feasible. Never create a problem merely to fill the structure. Do not repeat a low-level handling verb in adjacent scenes: each beat must change the product, material, actor state or viewer information. At least one middle scene needs two causal timed phases (setup/contact, then the visible result). Client examples supply only this abstract rhythm, never their plot, actors, products, words or claims. "
		"RULES: "
		"1) Use roster keys only in cast and products; in prose describe subjects visually (e.g. 'the bear mascot'), never by key. Each identity is exactly ONE subject and cast always uses its canonical roster key, never a pose or alternate-view key. CAST DECLARES WHO ACTS, NOT THE OPENING POSE. Write the supported body state and action the scene requires, even if it differs from the supplied photograph; after the script is accepted, pose preparation selects or generates the needed Character view before any storyboard image is made. Only roster actors appear in prose and cast (example scripts' characters do not exist here); no human or hand unless a Person is supplied. "
		"2) Every shot that shows the hero product uses the same roster product; never change its package, colour, print or construction. Do not translate or invent printed words. Once a consumable piece has been physically removed, a close action shot of only that detached piece and the actor may leave products empty so the image generator does not introduce a second container. Keep the product reference in any shot where the package or hero object is actually visible, especially the opening and final packshot. Set product_view for the package orientation needed in the opening frame, independently of the room camera. A changed angle must also be described in visual_camera. Use source for an unchanged package orientation or when no package is visible. If the product is visible in multiple scenes, plan at least one distinct package-facing view where the camera and object placement make that view physically possible; preserve the established orientation across continuous handling unless an action turns the package or a camera cut changes the viewpoint. Client-requested angles must be assigned to product-visible openings. Product-view preparation follows this script. Do not claim unseen printed panels are factual. "
		"3) The supplied characters are the protagonists who perform the product actions. Open on a visible event already happening. Each non-final scene completes ONE tangible interaction (grip, take out, open, press, place, carry, apply...) with a visible result; combine reach and grab in one scene; no scene of only looking, posing, smiling, thumbs-up or walking. Put a brief reaction after a completed interaction in that same scene, never in its own scene. "
		"4) Prerequisites first: take an item out before using it; used material never returns to the pack; objects keep their state across cuts. For a package that must appear on a table in later shots, prefer keeping the whole package on that table throughout and manipulating only its removable contents. If an actor picks up the package itself, a later table shot requires a timed action that visibly places the package back on its support before that cut. "
		"5) "
		+ effect_rule
		+ "6) Each scene is ONE continuous shot in ONE place: no split screens, montages or location changes inside a scene. A character keeps its weight on a support (floor or seat); one place keeps one identical description. "
		"7) The last scene is a stable product packshot with readable original print and the CTA from mandatories. For a static hero view, leave cast empty and place the original product on a real supporting surface so source artwork can remain exact; include a supplied actor in the closing shot only when that actor performs a meaningful visible product action. The on_screen_text field is only for an added viewer-facing overlay/CTA; do not transcribe or translate the physical package's logo, specifications or printed copy into that field. Source artwork owns those printed details. "
		"8) action is timed phases '[0-1.5s] ...' from 0 to the scene end, no gaps and no camera words. visual_camera is the opening composition only: a state one still picture can show. Preserve any grip, material location and support established by the preceding scene; never reset a carried product onto a table without placement. A new acquisition begins before its first contact, while an ongoing use begins in its retained state. Broad shots establish connected anatomy and support. Product close-ups show the focal material, original limb shape and contact area; the rest of the body may remain naturally outside the frame. Vary coverage with purpose. "
		"9) State only approved_claims from this product's brief; example scripts supply style, never product facts, certifications or performance claims. Sounds follow visible actions. Music must name concrete instruments, tempo and arrangement changes tied to visible beats, with a resolved ending; 'lively music' alone is insufficient. "
		"10) Give action scenes chronological beats completing one interaction and show each demonstration once. Choose scene count and phase timings from the requested duration, visible action and workflow frame capacity. If duration is Auto, choose it from the number of distinct feasible actions for these identities, objects and approved claims, not from an example video's length or the photographed pose alone. Open with a supplied subject already completing a tangible product interaction; a camera moving toward a static product is not an action hook. Do not spend the hook on noticing, walking or waiting. Never pad with filler. Scene durations are relative weights. Write a different premise from PRIOR CONCEPTS. "
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
	if revision and all(note.get("scene") for note in revision.get("notes") or []):
		# Scene-level notes edit named scenes in place: the shot list, its timing and its
		# pictures stay, so the scene count is the reviewed script's, not a new minimum.
		count = len(revision["script"].get("scenes") or [])
		if count:
			schema["properties"]["scenes"].update(minItems=count, maxItems=count)
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
		# Translation and presentation metadata belong to the returned copy. If a
		# translation needs repair, the next writer attempt must see English source
		# lines rather than an already localized, partially accepted screenplay.
		script = copy.deepcopy(script)
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
			display_names(script, viewer_language, _local_product_name(project))
		# Automatic delivery must not turn subjective reviewer or translation
		# advice into a manual approval stop. The structurally validated script and
		# its unresolved notes remain visible together for later assessment.
		if require_clean and script.get("director_notes"):
			script.setdefault(
				"writer_fallback",
				{
					"reason": "Bounded revisions left advisory findings on a structurally valid screenplay.",
					"quality_review": "deferred",
				},
			)
		return unique_scene_names(script)

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
			# chain. Allow one fresh proposal before stopping the bounded job, but
			# retain the original Director/reviewer defects. Dropping ``error`` here
			# previously let a fresh concept forget the reason the prior screenplay
			# was rejected.
			repair_context = error
			latest_script = None
			error = (
				repair_context
				+ "\nThe prior concept remained invalid after three repairs. Write a new premise and action chain that follows every invariant and every quoted defect."
			)
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
				"Mechanical staging notes belong in continuity_rules. Fix a defect by changing what "
				"visibly happens; never add a sentence asserting that it is fixed. Return the complete schema.\n"
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
		if project.total_duration_seconds is None and constraints.get("duration_seconds") is not None:
			request_prompt += (
				f"\nFROZEN AUTOMATIC TIMING: exactly {constraints['duration_seconds']:g} seconds and "
				f"at least {schema['properties']['scenes']['minItems']} distinct scenes. "
				"Keep one completed interaction per scene; do not pad with idle shots."
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
			rejected.append({"attempt": _attempt + 1, "error": str(exc)})
			if best_valid is not None:
				break
			# Invalid model JSON is a transient writer output, not a reason to
			# stop the batch before its bounded repair attempts are exhausted.
			error = "\nReturn only one complete JSON object matching the requested schema. " + str(exc)
			continue
		try:
			if revision:
				result = _keep_unnoted_scenes(result, revision)
			# Keep the original full proposal as evidence even when frame allocation
			# fails before any scene has been compiled.
			latest_script = copy.deepcopy(result)
			_freeze_proposed_duration(constraints, schema, result)
			script = fit_generated_timing(
				result, constraints["duration_seconds"], fps, max_scene_frames=constraints["max_scene_frames"]
			)
			from joymedia.services.planning.product_views import apply_requested_view_sequence

			apply_requested_view_sequence(script, constraints.get("creative_direction"))
			wording = (
				english_production_text(script, viewer_language)
				+ normalize_product_wording(script, inventory)
				+ normalize_product_camera_inserts(script)
				+ normalize_static_final_packshot(script)
				+ normalize_early_closing_beat(script)
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
				script["review_unavailable"] = str(exc)[:200]
				frappe.logger("joymedia.creative").warning(
					"Automatic text review unavailable for %s: %s", project.get("name"), exc
				)
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


def _local_product_name(project):
	"""The product's name as the client wrote it (the project or its parent), not the writer's English one."""
	from joymedia.services.project.versions import family

	for candidate in (project, family(project)):
		name = candidate.get("product_name") or ""
		if VIETNAMESE.search(name) or name.isupper():
			return name
	return ""


def display_names(script, language, product_name=""):
	"""The title and scene names in the reviewer's language, for display only.

	Production keeps the English originals; a failed translation leaves the
	English shown rather than stopping the script. The product's own name in the
	reviewer's language is given as a term to keep, so it is never renamed.
	"""
	from joymedia.services.planning.production import _ask_planner

	source = [script.get("title") or ""] + [scene.get("beat_name") or "" for scene in script["scenes"]]
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
	try:
		result = _ask_planner(
			f"Write these commercial and scene titles in natural, everyday {language} for a marketer: short, "
			"plain words, no English jargon such as hook or CTA. The first line is the video title; the others "
			"are scene titles in order."
			+ (
				f' The product is called "{product_name}": use exactly this name for it.'
				if product_name
				else ""
			)
			+ "\nTITLES: "
			+ json.dumps(source, ensure_ascii=False),
			system="You write short, faithful titles. Return only the requested JSON.",
			capability="translator",
			sampling_profile="scene_translation",
			response_schema=schema,
		)
		lines = result.get("lines") if isinstance(result, dict) else None
		if not (isinstance(lines, list) and len(lines) == len(source)):
			raise ValueError("Incomplete titles.")
	except Exception:
		frappe.log_error(title="Could not translate display names")
		return script
	script["display_title"] = lines[0].strip()
	for scene, name in zip(script["scenes"], lines[1:], strict=True):
		scene["display_name"] = name.strip()
	return script


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
	proper_name = re.compile(r"\b(?:[A-Z][a-z]{2,}\s+)+[A-Z][a-z]{2,}\b")

	def check(s, t):
		# Printed and brand names may remain in English inside an otherwise
		# translated line. Do not mistake a multiword proper name for untranslated copy.
		source_without_names = proper_name.sub("", s)
		translated_without_names = proper_name.sub("", t)
		return len(ENGLISH_WORDS.findall(translated_without_names)) < 2 and not _untranslated(
			source_without_names, translated_without_names, keep, language
		)

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


def normalize_static_final_packshot(script):
	"""Keep an inactive actor out of a product-only closing presentation."""
	scenes = script.get("scenes") or []
	if not scenes:
		return []
	scene = scenes[-1]
	if (
		not scene.get("cast")
		or not scene.get("products")
		or TANGIBLE_ACTION.search(scene.get("action") or "")
	):
		return []
	duration = float(scene["duration_seconds"])
	scene.update(
		cast=[],
		visual_camera="A close view of the original product in its established location; its printed front faces the camera and no actor is visible.",
		action=f"[0-{duration:g}s] The original product remains in its established position with its printed artwork intact.",
		visible_change="The original product remains in its established position with its printed artwork intact.",
		continuity_rules="Preserve the product's established physical support and original artwork. No actor appears in this shot.",
		shot_framing="close_up",
		subject_motion="stationary",
	)
	return ["Final packshot: removed an inactive actor and retained the product's established support."]


PRODUCT_CONTAINER_WORDS = re.compile(r"\b(?:tissue\s+)?(box|boxes|carton|cartons)\b", re.I)


def normalize_early_closing_beat(script):
	"""A packshot/CTA named before the last scene: the final product scene takes the CTA instead.

	Writers used to six-scene films end the story on scene six even when a seventh
	follows. Renaming that beat and carrying its on-screen CTA to the final product
	scene keeps the story and avoids spending every repair on the same structure.
	"""
	scenes = script.get("scenes") or []
	if len(scenes) < 3 or not scenes[-1].get("products"):
		return []
	changes = []
	for index, scene in enumerate(scenes[:-1], 1):
		if not CLOSING_BEAT.search(scene.get("beat_name") or ""):
			continue
		final = scenes[-1]
		if (
			str(scene.get("on_screen_text") or "").strip()
			and not str(final.get("on_screen_text") or "").strip()
		):
			final["on_screen_text"], scene["on_screen_text"] = scene["on_screen_text"], ""
		scene["beat_name"] = (
			" ".join(CLOSING_BEAT.sub("product", scene["beat_name"]).split()) or "Product moment"
		)
		if not CLOSING_BEAT.search(final.get("beat_name") or ""):
			final["beat_name"] = "Packshot CTA"
		changes.append(f"Scene {index}: the closing CTA moved to final scene {len(scenes)}.")
	return changes


def normalize_product_wording(script, inventory):
	"""Use 'pack' for packaging unless the reference verifies a rigid container.

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
	style = script.get("visual_style") or ""
	if FLAT_MEDIUM.search(style):
		kept = [part for part in re.split(r"(?<=[,.;])\s+", style) if not FLAT_MEDIUM.search(part)]
		script["visual_style"] = (
			" ".join(kept).strip(" ,;") or "Soft directional lighting with a coherent palette."
		)
		changes.append("visual_style: removed a flat drawing medium; the reference photos set the medium.")
	pack_without_rigid_evidence = any(
		item["role"] == "Product"
		and any(
			"construction: flexible" in str(v.get("description") or "").lower()
			or (
				re.search(
					r"\b(?:pack|package|pouch|wrapper|wrapping)\b", str(v.get("description") or ""), re.I
				)
				and "construction: rigid" not in str(v.get("description") or "").lower()
			)
			for v in item.get("views") or []
		)
		for item in inventory
	)
	if not pack_without_rigid_evidence:
		return changes
	for index, scene in enumerate(script["scenes"], 1):
		for field in ("visual_camera", "action", "visible_change", "continuity_rules"):
			text = scene.get(field) or ""
			fixed = PRODUCT_CONTAINER_WORDS.sub(
				lambda m: "packs" if m.group(1).lower().endswith("s") else "pack", text
			)
			if fixed != text:
				scene[field] = fixed
				changes.append(
					f"Scene {index} {field}: used pack because rigid construction was not evidenced."
				)
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


# A shot whose contact must stay perfectly readable (and a liquid or tearing effect) keeps a still camera;
# every other shot may move. The render compiler locks the same precision moments again.
PRECISION_STAGES = {"grip", "extract", "unfold", "inspect", "detail"}
EFFECT_ACTION = re.compile(
	r"\b(?:wipe|dab|blot|spill|pour|tear|stretch|pull|extract|unfold|open|peel|grip)\w*\b", re.I
)
# A 30-second film cut as six equal 5-second shots has no rhythm. Plan scenes at most 85% of a shot's
# capacity so lengths can vary: a quick hook, the longest proof beat, short detail cutaways.
PACING_HEADROOM = 0.85
DEMO_VERBS = re.compile(
	r"\b(examin|inspect|present|show|wip|dab|blot|pull|extract|unfold|fold|tear|smell|sniff|touch|feel|squeez|press|rub|"
	r"open|hug|cuddl)(?:e|es|ed|ing|s)?\b",
	re.I,
)
STORY_OBJECT = re.compile(
	r"\b(tissues?|sheets?|packs?|packages?|box(?:es)?|napkins?|cookies?|crumbs?|mouth|face|nose|cheeks?|paws?|hands?|"
	r"table|surface|spill|stain)\b",
	re.I,
)
ABSORB = re.compile(r"\b(?:absorb|soak)\w*\b", re.I)
# When the writer weights every scene alike, the film has no rhythm. Weight each scene by its job
# instead: the proof longest, the hook, reaction and close quick.
JOB_WEIGHTS = {
	"establish": 0.85,
	"approach": 0.8,
	"grip": 0.8,
	"extract": 0.9,
	"unfold": 0.9,
	"detail": 1.15,
	"inspect": 0.9,
	"feel": 0.7,
	"present": 0.85,
	"hero": 0.8,
}


def _precise_contact(scene):
	# The same precision moments the render compiler locks (planning/camera.py): a close-up
	# reaction or presentation may still push in; a product-only shot has no contact to protect.
	return (
		(scene.get("shot_framing") == "extreme_close_up" and bool(scene.get("cast")))
		or scene.get("narrative_stage") in PRECISION_STAGES
		# In a wide shot the contact is small: a gentle move does not hide it.
		or (
			scene.get("shot_framing") not in {"wide", "full"}
			and bool(EFFECT_ACTION.search(scene.get("action") or ""))
		)
	)


def _demonstrations(scene):
	"""(verb, object) pairs a scene demonstrates, e.g. ("examin", "tissue")."""
	text = re.sub(r"\[[^\]]*\]", " ", scene.get("action") or "")
	pairs = set()
	for match in DEMO_VERBS.finditer(text):
		target = STORY_OBJECT.search(" ".join(text[match.end() :].split()[:6]))
		if not target or re.match(r"\s*(?:it|them)\b", text[match.end() :]):
			# "holds the tissue up to examine it": the object is the one named before, in this sentence.
			earlier = list(STORY_OBJECT.finditer(re.split(r"[.;!?]", text[: match.start()])[-1]))
			target = earlier[-1] if earlier else target
		if target:
			pairs.add((match.group(1).lower(), target.group(1).lower().rstrip("s")))
	return pairs


def story_logic_errors(scenes):
	"""Objective story faults: the same demonstration twice, or an effect with no physical cause."""
	# Detect identical adjacent action sequences even for products whose names are
	# outside the vocabulary used by the more specific demonstration check.
	# Leave the final packshot to the existing closing-scene checks.
	for index in range(1, len(scenes) - 1):
		previous, current = scenes[index - 1], scenes[index]

		def normalized_action(scene):
			return " ".join(re.sub(r"\[[^\]]*\]", " ", str(scene.get("action") or "")).casefold().split())

		before, after = normalized_action(previous), normalized_action(current)
		if before and before == after:
			return (
				f"Scenes {index} and {index + 1} repeat the same action sequence. "
				"Give the later scene a distinct action or visible result."
			)
	seen = {}
	for index, scene in enumerate(scenes[:-1], 1):
		for pair in _demonstrations(scene):
			if pair in seen:
				return (
					f"Scenes {seen[pair]} and {index} repeat the same demonstration ({pair[0]} the {pair[1]}). "
					f"Replace scene {index} with a new beat that moves the story: a different action, a visible "
					"result, a reaction or a reveal."
				)
			seen[pair] = index
	wet = False
	for index, scene in enumerate(scenes, 1):
		action = scene.get("action") or ""
		if ABSORB.search(action) and not wet and not WET_EVENT.search(action):
			return (
				f"Scene {index} has something absorbed or soaked up, but no liquid exists on camera. A tissue absorbs "
				"only liquid: show the spill or drops first, or describe wiping crumbs away instead."
			)
		wet = wet or bool(WET_EVENT.search(action))
	return None


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

	coverage_for = {
		"establish": ("wide", "oblique"),
		"approach": ("medium", "over_shoulder"),
		"grip": ("medium_close_up", "high_angle"),
		"extract": ("close_up", "oblique"),
		"unfold": ("extreme_close_up", "overhead"),
		"inspect": ("close_up", "over_shoulder"),
		"detail": ("extreme_close_up", "overhead"),
		"feel": ("medium_close_up", "eye_level"),
		"present": ("medium", "low_angle"),
		"hero": ("close_up", "low_angle"),
	}

	def change_coverage(index, framing, angle, reason):
		scene = scenes[index]
		old = (scene.get("shot_framing"), scene.get("shot_angle"))
		if old != (framing, angle):
			scene["shot_framing"], scene["shot_angle"] = framing, angle
			changes.append(
				f"Scene {index + 1}: coverage {old[0] or 'unset'}/{old[1] or 'unset'} -> {framing}/{angle} ({reason})."
			)

	for index, scene in enumerate(scenes):
		motion = scene_motion(scene)
		stage = scene.get("narrative_stage")
		if index and (scene.get("shot_framing"), scene.get("shot_angle"), scene.get("camera_move")) == (
			scenes[index - 1].get("shot_framing"),
			scenes[index - 1].get("shot_angle"),
			scenes[index - 1].get("camera_move"),
		):
			framing, angle = coverage_for.get(stage, ("medium_close_up", "oblique"))
			change_coverage(index, framing, angle, "avoid repeated adjacent coverage")
		if motion == "contact":
			if _precise_contact(scene):
				change(index, "static", "keep precise physical contact readable")
			elif scene.get("camera_move") not in CAMERA_MOVES:
				change(index, "static", "fill a missing camera choice")
		elif motion == "locomotion":
			change(index, "tracking", "follow subject travel")
		else:
			preference = preferences.get(scene.get("narrative_stage"), {})
			move = move_for.get(preference.get("behavior"))
			if move:
				change(index, move, "the supplied reference grammar for this narrative job")
			elif scene.get("camera_move") not in CAMERA_MOVES:
				change(index, "dolly_in" if motion == "detail" else "static", "fill a missing camera choice")

	# Resolve camera variety here, after the action is accepted. A writer's
	# mostly static proposal must not force another screenplay or a flat film:
	# the opening moves, no more than two still shots follow each other, about
	# half the film moves, and angles leave eye level where the job suits it.
	def free(index):
		return (
			scenes[index].get("camera_move") == "static"
			and not _precise_contact(scenes[index])
			and (scene_motion(scenes[index]) != "locomotion")
		)

	def expressive(index):
		scene, last = scenes[index], index == len(scenes) - 1
		if last:
			return "dolly_out"
		if index == 0:
			return (
				"arc"
				if scene.get("cast") and scene.get("shot_framing") in {"wide", "full", "medium"}
				else "dolly_in"
			)
		if scene.get("narrative_stage") == "approach":
			return "truck_right" if index % 2 else "truck_left"
		if scene.get("narrative_stage") in {"feel", "inspect"}:
			return "dolly_in"
		return "arc" if scene.get("shot_framing") in {"wide", "full"} else "dolly_in"

	if scenes and free(0):
		change(0, expressive(0), "open on a moving hook")
	for index in range(2, len(scenes)):
		if all(scenes[i].get("camera_move") == "static" for i in range(index - 2, index + 1)):
			middle = next((i for i in (index - 1, index, index - 2) if free(i)), None)
			if middle is not None:
				change(middle, expressive(middle), "break a run of still shots")
	target = math.ceil(len(scenes) / 2)
	for index in sorted(range(len(scenes)), key=lambda i: (i not in {0, len(scenes) - 1}, i)):
		if sum(scene.get("camera_move") != "static" for scene in scenes) >= target:
			break
		if free(index):
			change(index, expressive(index), "give the film enough camera movement")
	if sum(scene.get("shot_angle") in {None, "", "eye_level"} for scene in scenes) > len(scenes) / 2:
		for index, scene in enumerate(scenes):
			wanted = coverage_for.get(scene.get("narrative_stage"), (None, None))[1]
			if scene.get("shot_angle") in {None, "", "eye_level"} and wanted not in {None, "eye_level"}:
				old = scene.get("shot_angle")
				scene["shot_angle"] = wanted
				changes.append(
					f"Scene {index + 1}: angle {old or 'unset'} -> {wanted} (vary the eye-level coverage)."
				)
				if (
					sum(item.get("shot_angle") in {None, "", "eye_level"} for item in scenes)
					<= len(scenes) / 2
				):
					break
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
	# A client's explicit shot count is a delivery constraint, even when the
	# automatic writer is allowed to retain non-critical quality notes.
	direction = str(constraints.get("creative_direction") or "")
	requested_count = re.search(
		r"\b(?:make|create|write|plan)\b.{0,50}?\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)(?:[- ](?:distinct[- ])?)?(?:shots?|scenes?)\b"
		r"|\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)[- ](?:shots?|scenes?)\b",
		direction,
		re.I,
	)
	if requested_count:
		word = (requested_count.group(1) or requested_count.group(2)).casefold()
		count = (
			int(word)
			if word.isdigit()
			else ("one two three four five six seven eight nine ten".split().index(word) + 1)
		)
		if len(script["scenes"]) != count:
			raise ValueError(f"The brief requests {count} shots; write exactly {count} scenes.")
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
		# A shot cannot begin already holding the object its action acquires.
		# Compare the script's own opening rule to its action before compiling
		# either into a first frame; this catches a self-contradiction that a
		# general prose reviewer may overlook.
		opening_text = "\n".join(
			str(scene.get(field) or "") for field in ("visual_camera", "continuity_rules")
		)
		object_pattern = r"([a-z][a-z\s-]{0,50}?)(?=\s+(?:and|while|before)\b|[.,;\n]|$)"
		holds = re.findall(r"\b(?:holding|holds)\s+(?:the|a|an)\s+" + object_pattern, opening_text, re.I)
		acquires = re.findall(
			r"\b(?:reaches?\s+for|grabs?|grasps?|picks?\s+up)\s+(?:the|a|an)\s+" + object_pattern,
			scene["action"],
			re.I,
		)
		for held in holds:
			held_words = held.lower().split()
			for acquired in acquires:
				acquired_words = acquired.lower().split()
				# Allow a brand or colour modifier in one phrase, but require the
				# same final object words. Two different cups must not be conflated.
				shared = min(2, len(held_words), len(acquired_words))
				if held_words[-shared:] == acquired_words[-shared:] and (
					shared == 2 or held_words == acquired_words
				):
					raise ValueError(
						f"Scene {scene_index + 1} opens holding {held.strip()} but its action acquires {acquired.strip()}; stage the object on a reachable support until the grasp."
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
				f"[{phase['start']:g}-{phase['end']:g}s] {clean}"
				for phase, clean in zip(phases, cleaned, strict=True)
			)
			phases = read_timed_actions(scene["action"], duration)
		if (
			"action_reference_observations" in constraints
			and not constraints["action_reference_observations"]
			and not AUTHORED_PHYSICAL_EFFECT.search(
				" ".join((constraints.get("mandatories") or "", constraints.get("creative_direction") or ""))
			)
			and UNANCHORED_PHYSICAL_EFFECT.search(scene["action"])
		):
			raise ValueError(
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
		# A selected seated image is an identity reference, not an immutable
		# animation rig. The pose-coverage pass after planning chooses an
		# existing mobile view or routes a new supported keyframe through Klein.
		for field in ("voice_over", "audio_cues", "on_screen_text"):
			if not isinstance(scene.get(field, ""), str):
				raise ValueError("Scene audio and text must be strings.")
	_validate_product_support_continuity(script["scenes"])
	_validate_character_support_continuity(script["scenes"], reference_options)
	try:
		_validate_action_progress(script["scenes"])
	except ValueError as exc:
		heuristic(str(exc))
	for finding in commercial_action_findings(script["scenes"], total):
		heuristic(finding)
	# The director sometimes writes an actor as the subject of a timed action
	# while leaving cast empty. Repair the unambiguous single-character case
	# before reference binding; otherwise a product-only frame can be marked
	# Passed even though it cannot perform the scripted action.
	actors = [
		(key, value.get("identity") or key)
		for key, value in reference_options.items()
		if value.get("role") in {"Character", "Person"}
	]
	for scene in script["scenes"]:
		if scene.get("cast") or not re.search(
			r"(?:^|\n)\s*\[[^]]+\]\s*(?:the|a|an)?\s*(?:mascot|character|bear)\b",
			scene.get("action") or "",
			re.I,
		):
			continue
		if len({identity for _, identity in actors}) == 1 and actors:
			scene["cast"] = [actors[0][0]]
	closing = script["scenes"][-1]
	closing_actor = not closing.get("cast") and re.search(
		r"^\s*\[[^]]+\]\s*(?:the|a|an)?\s*(?:mascot|character|actor|person|woman|man|bear)\b",
		closing.get("action") or "",
		re.I,
	)
	if closing_actor and TANGIBLE_ACTION.search(closing.get("action") or ""):
		# A single supplied identity makes an omitted cast key unambiguous. Keep
		# the authored action and let the normal frame/physics checks inspect it.
		actors = [
			(key, value.get("identity") or key)
			for key, value in reference_options.items()
			if value.get("role") in {"Character", "Person"}
		]
		if len({identity for _, identity in actors}) == 1 and actors:
			closing["cast"] = [actors[0][0]]
	if closing_actor and not closing.get("cast"):
		raise ValueError(
			"The closing scene describes an actor action but declares no cast. "
			"Either include the supplied actor and complete a product action, or write a product-only hero shot."
		)
	if (
		closing.get("products")
		and closing.get("cast")
		and not TANGIBLE_ACTION.search(closing.get("action") or "")
	):
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
	if total >= 20:
		spoken = [
			index
			for index, scene in enumerate(script["scenes"])
			if str(scene.get("voice_over") or "").strip()
		]
		if len(spoken) < 3:
			raise ValueError(
				"A commercial of twenty seconds or more needs at least three short voice-over lines: an opening hook, a product/benefit message, and a closing CTA."
			)
		if 0 not in spoken:
			raise ValueError("The opening scene needs a short marketing voice-over hook.")
		if not any(0 < index < len(script["scenes"]) - 1 for index in spoken):
			raise ValueError("Include a short approved product or benefit voice-over message before the CTA.")
		if not any(index >= len(script["scenes"]) - 2 for index in spoken):
			raise ValueError(
				"Put the closing marketing CTA in voice-over during one of the final two scenes."
			)
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
	wet_happened = False
	for index, scene in enumerate(script["scenes"], 1):
		for phase in read_timed_actions(scene["action"]) or [{"action": scene["action"]}]:
			if re.search(
				r"\b(?:discard|discards|throw|throws|toss|tosses)\b", phase["action"], re.I
			) and not re.search(
				r"\b(?:into|onto|on|in)\s+(?:a|an|the)?\s*(?:visible\s+)?(?:bin|basket|tray|table|counter|surface|container|floor)\b",
				phase["action"],
				re.I,
			):
				raise ValueError(
					f"Scene {index} discards an object without a visible destination and physical support. "
					"Name its supported destination or keep it visibly in the actor's paw."
				)
			missing_cause = MESS.search(phase["action"]) or WET_CLEANUP.search(phase["action"])
			wet_cleanup = WET_CLEANUP.search(phase["action"])
			if wet_cleanup and not wet_happened and not WET_EVENT.search(phase["action"]):
				raise ValueError(
					f'Scene {index} cleans a wet surface that never became wet on camera ("{wet_cleanup.group(0)}"); show the liquid event first.'
				)
			if missing_cause and not happened and not MESS_EVENT.search(phase["action"]):
				raise ValueError(
					f'Scene {index} cleans a mess that never happened on camera ("{missing_cause.group(0)}"); show it being made in an earlier action phase or scene first.'
				)
			happened = happened or bool(MESS_EVENT.search(phase["action"]))
			wet_happened = wet_happened or bool(WET_EVENT.search(phase["action"]))
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
	story_error = story_logic_errors(script["scenes"])
	if story_error:
		raise ValueError(story_error)
	cast = {key for scene in script["scenes"] for key in scene["cast"]}
	characters = [item for item in inventory if item["role"] in {"Character", "Person"}]
	if characters and not any(
		view.get("key", item["key"]) in cast
		for item in characters
		for view in item.get("views") or [{"key": item["key"]}]
	):
		raise ValueError(
			"The supplied character never appears; use at least one supplied character as the protagonist who performs the product actions."
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
