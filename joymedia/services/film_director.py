"""Cinematic planning rules for character + location films.

A "story film" is a project whose references contain at least one character
(talent) image and at least one place image. It is planned as a few long,
continuous takes rendered with MiniMax H3 Reference-to-Video, where every take
receives the character as <Picture 1> and a location as <Picture 2>.
"""

import math
import re

import frappe


CHARACTER = "character"
PLACE = "place"
OTHER = "other"

CHARACTER_ROLES = {"character"}
PLACE_ROLES = {"environment", "composition"}
CHARACTER_CATEGORIES = {"character"}
PLACE_CATEGORIES = {"background"}

PERSON_PATTERN = re.compile(
	r"\b(she|her|hers|he|his|him|woman|man|girl|boy|person|character|couple|family)\b",
	re.I,
)
WORD_PATTERN = re.compile(r"[a-z]+")

MIN_TAKE_SECONDS = 5
MAX_TAKE_SECONDS = 10
MAX_TAKES = 6
# MiniMax H3 renders at least 124 frames at 24 fps; shorter takes waste the extra render.
MIN_RENDER_SECONDS = 124 / 24

DIRECTOR_RULES = """
You are the film director for JoyMedia commercials. Plan a short cinematic film
that follows the character through the supplied places, not a slideshow.

STRUCTURE
- Plan {min_takes} to {max_takes} long continuous takes of {min_take}-{max_take} seconds each.
- The character appears in EVERY take except an optional final establishing take.
- Order the places so the film has a clear progression (for example outside to inside,
  public to private, or day to night). End on a wide establishing view of the main place.
- Every take except the last ends with a transition move that hides the cut to the
  next take: the camera pushes through a window or doorway, light sweeps across the
  frame, or a whip pan.
- Vary wardrobe, performance and camera move between takes; never repeat an action.
- Match the look (light, colour grade, mood) to the VIDEO IDEA and GLOBAL INSTRUCTIONS.
  If none is given, use soft natural cinematic light and a gentle filmic grade. Keep
  the same look in every take.

EVERY generation_prompt (English, 60-110 words) states, in this order:
1. The person from <Picture 1>: wardrobe for this take and their performance.
   Keep their face, hair and body identical to <Picture 1>.
2. The place from <Picture 2>: keep its exact layout, architecture, furniture and
   materials.
3. One clear camera move: slow push-in, rack focus, gentle orbit, dolly, tracking
   shot, crane or drone move.
4. Light, grade and depth of field.
5. The transition, if any, then the constraints: photorealistic, smooth stabilized
   motion, no text, no logos, no extra people, no face or structure deformation.

REFERENCES
- Every take lists exactly two references: first the character key, then one place
  key. A take without the character lists two place keys that appear in it.
- Use only the supplied keys.
""".strip()

FEW_SHOT_EXAMPLE = (
	"EXAMPLE generation_prompt: The person from <Picture 1>, wearing a light linen shirt, walks "
	"slowly through the place from <Picture 2>, pauses by the window and looks out with a quiet "
	"smile. Keep their face and hair identical to <Picture 1> and the exact layout and materials "
	"of <Picture 2>. Slow dolly-in at eye level. Soft morning light, natural filmic grade, shallow "
	"depth of field. The take ends as the camera pushes through the window into bright light. "
	"Photorealistic, smooth stabilized motion, no text, no logos, no deformation."
)


def take_count_range(total_seconds):
	"""Return the (min, max) number of takes that keeps every take within the model's range."""
	total = max(float(total_seconds or 0), MIN_TAKE_SECONDS)
	minimum = max(2, math.ceil(total / MAX_TAKE_SECONDS))
	maximum = max(minimum, min(MAX_TAKES, math.floor(total / MIN_TAKE_SECONDS)))
	return min(minimum, MAX_TAKES), maximum


def classify_reference(context):
	"""Return CHARACTER, PLACE or OTHER for one project reference context."""
	if (context.get("media_type") or "Image") != "Image":
		return OTHER
	analysis = context.get("analysis") if isinstance(context.get("analysis"), dict) else {}
	kind = str(analysis.get("kind") or "").strip().lower()
	if kind == "person":
		return CHARACTER
	if kind == "place":
		return PLACE
	role = str(context.get("reference_role") or "").strip().lower()
	category = str(context.get("asset_category") or "").strip().lower()
	if role in CHARACTER_ROLES or category in CHARACTER_CATEGORIES:
		return CHARACTER
	if role in PLACE_ROLES or category in PLACE_CATEGORIES:
		return PLACE
	return OTHER


def balance_take_durations(shots, total_seconds):
	"""Keep every take renderable (MIN_RENDER_SECONDS-MAX_TAKE_SECONDS) while preserving the total.

	Takes keep their planned proportions where possible. When the total cannot give
	every take the minimum length, the shortest middle takes are dropped.
	"""
	total = float(total_seconds or 0)
	if not shots or total <= 0:
		return shots
	shots = list(shots)
	while len(shots) > 2 and len(shots) * MIN_RENDER_SECONDS > total:
		middle = min(range(1, len(shots) - 1), key=lambda index: float(shots[index]["duration_seconds"]))
		shots.pop(middle)
	low = min(MIN_RENDER_SECONDS, total / len(shots))
	high = max(MAX_TAKE_SECONDS, total / len(shots))
	weights = [max(float(shot["duration_seconds"]), 0.001) for shot in shots]

	def lengths(scale):
		return [min(max(scale * weight, low), high) for weight in weights]

	# sum(lengths(scale)) grows monotonically with scale and spans [n*low, n*high],
	# which contains the total by construction, so bisection converges on it.
	lower, upper = 0.0, high / min(weights)
	for _ in range(100):
		middle = (lower + upper) / 2
		if sum(lengths(middle)) < total:
			lower = middle
		else:
			upper = middle
	for shot, length in zip(shots, lengths(upper)):
		shot["duration_seconds"] = length
	# Remove the bisection residue so the takes sum exactly to the total.
	shots[-1]["duration_seconds"] = total - sum(shot["duration_seconds"] for shot in shots[:-1])
	for number, shot in enumerate(shots, start=1):
		shot["shot_number"] = number
	return shots


def build_roster(reference_contexts):
	"""Split project references into character and place lists, keeping project order."""
	roster = {CHARACTER: [], PLACE: [], OTHER: []}
	for context in reference_contexts or []:
		if not context.get("reference_key"):
			continue
		roster[classify_reference(context)].append(context)
	return roster


def is_story_film(reference_contexts):
	roster = build_roster(reference_contexts)
	return bool(roster[CHARACTER] and roster[PLACE])


def build_director_instruction(reference_contexts, reference_role, total_seconds):
	"""Return the planner instruction for a story film, including the reference roster."""
	roster = build_roster(reference_contexts)
	min_takes, max_takes = take_count_range(total_seconds)
	lines = [
		DIRECTOR_RULES.format(
			min_takes=min_takes,
			max_takes=max_takes,
			min_take=MIN_TAKE_SECONDS,
			max_take=MAX_TAKE_SECONDS,
		),
		"",
		f'Every reference you list must use usage_role "{reference_role}".',
		"",
		"CHARACTER",
	]
	lines.extend(_roster_line(context) for context in roster[CHARACTER])
	lines.append("PLACES")
	lines.extend(_roster_line(context) for context in roster[PLACE])
	lines.extend(["", FEW_SHOT_EXAMPLE])
	return "\n".join(lines)


def normalize_story_references(shots, reference_contexts, reference_role):
	"""Make every shot reference exactly two images, in <Picture 1>/<Picture 2> order.

	The order is load-bearing: the first reference is bound to <Picture 1> and the
	second to <Picture 2> by the Reference-to-Video workflow bindings. The planner's
	prompt text decides the order, because models often omit or reorder keys:
	a take that shows a person gets [character, place]; otherwise [place, place],
	with the place the prompt describes as <Picture 2>.
	"""
	roster = build_roster(reference_contexts)
	if not roster[CHARACTER] or not roster[PLACE]:
		return shots
	character_key = roster[CHARACTER][0]["reference_key"]
	places = roster[PLACE]
	place_keys = {context["reference_key"] for context in places}
	for shot in shots:
		if not isinstance(shot, dict):
			continue
		prompt = str(shot.get("generation_prompt") or "")
		listed = [
			str((reference or {}).get("reference_key") or "").strip()
			for reference in shot.get("references") or []
		]
		candidates = [context for context in places if context["reference_key"] in listed] or places
		best_place = _best_matching_place(prompt, candidates)
		if PERSON_PATTERN.search(prompt):
			ordered = [character_key, best_place]
		else:
			others = [key for key in listed if key in place_keys and key != best_place]
			fallback = next(context["reference_key"] for context in places if context["reference_key"] != best_place) \
				if len(places) > 1 else character_key
			ordered = [others[0] if others else fallback, best_place]
		shot["references"] = [{"reference_key": key, "usage_role": reference_role} for key in ordered]
	return shots


def _best_matching_place(prompt, places):
	"""Return the key of the place whose key or description words best match the prompt."""
	prompt_words = set(WORD_PATTERN.findall(prompt.lower()))

	def score(context):
		analysis = context.get("analysis") if isinstance(context.get("analysis"), dict) else {}
		text = " ".join(
			str(value or "")
			for value in (context.get("reference_key"), context.get("label"), context.get("asset_name"), analysis.get("description"))
		).replace("_", " ").lower()
		return len(prompt_words & {word for word in WORD_PATTERN.findall(text) if len(word) > 3})

	return max(places, key=score)["reference_key"]


def reference_preamble(shot_reference_versions, project_references):
	"""Explain <Picture N> tags for one shot, from its ordered Asset Versions."""
	by_version = {
		reference.get("asset_version"): reference
		for reference in project_references or []
		if reference.get("asset_version")
	}
	parts = []
	for index, asset_version in enumerate(shot_reference_versions[:9], start=1):
		reference = by_version.get(asset_version) or {}
		label = str(reference.get("label") or "").strip()
		suffix = f" ({label})" if label else ""
		kind = classify_reference(_asset_version_context(asset_version, reference))
		if kind == CHARACTER:
			parts.append(
				f"<Picture {index}> is the main character{suffix}: keep the face, hair and body identical."
			)
		elif kind == PLACE:
			parts.append(
				f"<Picture {index}> is the location{suffix}: keep its architecture, layout and materials exactly."
			)
		else:
			parts.append(
				f"<Picture {index}> is a reference subject{suffix}: keep its shape, colours and details exactly."
			)
	return " ".join(parts)


def _asset_version_context(asset_version, project_reference):
	"""Build the classify_reference input for an Asset Version from the database."""
	version = frappe.db.get_value(
		"Asset Version", asset_version, ["media_asset", "analysis_status", "analysis_json"], as_dict=True
	) or frappe._dict()
	asset = frappe.db.get_value(
		"Media Asset", version.media_asset, ["media_type", "asset_category"], as_dict=True
	) if version.media_asset else None
	analysis = {}
	if version.analysis_status == "Ready" and version.analysis_json:
		try:
			analysis = frappe.parse_json(version.analysis_json)
		except (TypeError, ValueError):
			analysis = {}
	return {
		"media_type": (asset or {}).get("media_type") or "Image",
		"asset_category": (asset or {}).get("asset_category"),
		"reference_role": project_reference.get("reference_role"),
		"analysis": analysis,
	}


def _roster_line(context):
	analysis = context.get("analysis") if isinstance(context.get("analysis"), dict) else {}
	description = str(analysis.get("description") or "").strip()
	if not description:
		description = " ".join(
			part for part in (context.get("label"), context.get("asset_name")) if part
		).strip()
	if isinstance(analysis.get("outfit"), str) and analysis["outfit"].strip():
		description += f"; outfit: {analysis['outfit'].strip()}"
	return f"- key={context['reference_key']}: {description[:220]}"

