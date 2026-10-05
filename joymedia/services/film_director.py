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
PICTURE_TAG_PATTERN = re.compile(r"<Picture\s*(\d+)>", re.I)
TAKE_CONSTRAINTS = (
	"One continuous shot with no cuts, photorealistic, smooth stabilized motion, no text, no logos, "
	"no deformation."
)

MIN_TAKE_SECONDS = 5
MAX_TAKE_SECONDS = 10
MAX_TAKES = 6
# MiniMax H3 renders at least 124 frames at 24 fps; shorter takes waste the extra render.
MIN_RENDER_SECONDS = 124 / 24
# A continuation job adding less footage than this is not worth its fixed overhead.
MIN_CONTINUATION_SECONDS = 2.0

DIRECTOR_RULES = """
You are the film director for JoyMedia commercials. Plan a short cinematic film
that follows the character through the supplied places, not a slideshow.

STRUCTURE
- Plan exactly {take_count} long continuous takes of {min_take}-{max_take} seconds each.
- Use a different place in each take, choosing the places that best tell the story;
  only the main place may appear twice (to open and to close the film).
- Each take is ONE unbroken camera shot in ONE place: no cuts, no montage, no
  second location inside the take.
- The character appears in EVERY take except an optional final establishing take.
- Follow the STORY ARC below: each take plays its beat, in order. Order the places so
  the journey makes sense (for example outside to inside, public to private) and put
  the most spectacular place on the CLIMAX take.
- The film is one continuous journey: each take starts where the previous one ended
  (the character arrives from the previous place, continuing the same direction and
  mood), and time of day may progress naturally (for example afternoon to dusk).
- Every take except the last ends with a camera move that hides the cut to the next
  take, inside the same place: a push toward a window or doorway, light sweeping
  across the frame, or a whip pan.
- The character keeps the outfit shown in <Picture 1> in every take unless the
  VIDEO IDEA asks for a change. Vary performance and camera move between takes;
  never repeat an action.
- Match the look (light, colour grade, mood) to the VIDEO IDEA and GLOBAL INSTRUCTIONS.
  If none is given, use soft natural cinematic light and a gentle filmic grade. Keep
  one consistent colour grade across all takes.
- shot_name is "<BEAT>: <short title>", e.g. "OPENING: Arrival at dusk". Keep the BEAT word
  in English; write the short title in the language of the VIDEO IDEA (Vietnamese for a
  Vietnamese idea, e.g. "OPENING: Dạo bước buổi sớm").

EVERY generation_prompt (English, 60-110 words) states, in this order:
1. The person from <Picture 1>: their outfit and their performance in this take.
   Keep their face, hair and body identical to <Picture 1>.
2. The place from <Picture 2>: keep its exact layout, architecture, furniture and
   materials. Describe only what its roster line says; if the roster has no
   description, write just "the place from <Picture 2>" and do not invent its contents.
3. One clear camera move: slow push-in, rack focus, gentle orbit, dolly, tracking
   shot, crane or drone move.
4. Light, grade and depth of field.
5. The transition, if any, then the constraints: one continuous shot with no cuts,
   photorealistic, smooth stabilized motion, no text, no logos, no extra people, no
   face or structure deformation.

REFERENCES
- Every take lists exactly two references: first the character key, then one place
  key. A take without the character lists its place key twice.
- Use only the supplied keys. Keys are names, not picture numbers: in the prompt the
  character is always <Picture 1> and the place is always <Picture 2>.
""".strip()

FEW_SHOT_EXAMPLE = (
	"generation_prompt TEMPLATE (fill every [ ] for its own beat and place; never reuse wording "
	"between takes): The person from <Picture 1>, in [outfit from <Picture 1>], [action that plays "
	"this take's beat] in the place from <Picture 2>, [what of that place is seen]. Keep their face "
	"and hair identical to <Picture 1> and the exact layout and materials of <Picture 2>. [One "
	"camera move]. [Light, grade and depth of field]. [How the take ends]. One continuous shot with "
	"no cuts, photorealistic, smooth stabilized motion, no text, no logos, no deformation."
)


STORY_BEATS = {
	"OPENING": "hook the viewer with a striking first image; introduce the character arriving and set "
	"the mood and time of day.",
	"BUILD": "the character explores and discovers; their delight and the camera energy grow.",
	"CLIMAX": "the emotional peak in the most spectacular place: the character's strongest moment "
	"(a big smile, arms open to the view, a signature gesture) with the boldest camera move; "
	"make it the longest take.",
	"RESOLUTION": "a quiet, intimate moment of belonging and contentment; slower camera, softer light.",
	"CLOSING": "the final image: the character's last look, or a wide establishing view of the main "
	"place, settling to stillness so the film ends cleanly.",
}


# Appended to the last shot of every plan: the planner often writes it like any other
# take, and the film then stops mid-motion instead of ending.
CLOSING_DIRECTION = (
	"This is the last shot of the film: the camera slowly pulls back and rises into a wide, calm "
	"final view, all motion settles to stillness and the light softens, so the film ends gracefully."
)


def close_the_film(shots):
	"""Make the last shot end the film; returns the shots."""
	if shots and isinstance(shots[-1], dict):
		prompt = str(shots[-1].get("generation_prompt") or "").strip()
		if prompt and CLOSING_DIRECTION not in prompt:
			shots[-1]["generation_prompt"] = f"{prompt} {CLOSING_DIRECTION}"
	return shots


def story_beats(take_count):
	"""Return the story beat of each take: an opening, a climax and a closing at every length."""
	if take_count <= 1:
		return ["OPENING"]
	if take_count == 2:
		return ["OPENING", "CLOSING"]
	if take_count == 3:
		return ["OPENING", "CLIMAX", "CLOSING"]
	if take_count == 4:
		return ["OPENING", "BUILD", "CLIMAX", "CLOSING"]
	return ["OPENING"] + ["BUILD"] * (take_count - 4) + ["CLIMAX", "RESOLUTION", "CLOSING"]


def take_count_range(total_seconds):
	"""Return the (min, max) number of takes that keeps every take within the model's range."""
	total = max(float(total_seconds or 0), MIN_TAKE_SECONDS)
	minimum = max(2, math.ceil(total / MAX_TAKE_SECONDS))
	maximum = max(minimum, min(MAX_TAKES, math.floor(total / MIN_TAKE_SECONDS)))
	return min(minimum, MAX_TAKES), maximum


def story_take_count(total_seconds, reference_contexts):
	"""Return how many takes to plan: one per place, within the duration's renderable range."""
	minimum, maximum = take_count_range(total_seconds)
	total = max(float(total_seconds or 0), MIN_TAKE_SECONDS)
	renderable = max(minimum, math.floor(total / MIN_RENDER_SECONDS))
	places = len(build_roster(reference_contexts)[PLACE])
	return max(minimum, min(places, maximum, renderable))


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
	_avoid_short_continuations(shots)
	# Remove the bisection residue so the takes sum exactly to the total.
	shots[-1]["duration_seconds"] = total - sum(shot["duration_seconds"] for shot in shots[:-1])
	for number, shot in enumerate(shots, start=1):
		shot["shot_number"] = number
	return shots


def _avoid_short_continuations(shots):
	"""Fit takes to whole render jobs without changing the film's length.

	A take renders MIN_RENDER_SECONDS in its first job and continues in further
	jobs, each with ~2.5 minutes of fixed overhead. A take just over one job long
	would spend a whole job on a second or less of footage, so it is trimmed to
	one job and the spare time goes to the climax (or the longest take), which
	the story wants longest anyway.
	"""
	single = MIN_RENDER_SECONDS
	spare = 0.0
	for shot in shots:
		length = float(shot["duration_seconds"])
		if single < length < single + MIN_CONTINUATION_SECONDS:
			spare += length - single
			shot["duration_seconds"] = single
	if not spare:
		return
	climax = next((shot for shot in shots if str(shot.get("shot_name") or "").upper().startswith("CLIMAX")), None)
	receivers = [climax] if climax else []
	receivers += sorted((shot for shot in shots if shot is not climax), key=lambda shot: -float(shot["duration_seconds"]))
	for shot in receivers:
		room = MAX_TAKE_SECONDS - float(shot["duration_seconds"])
		given = min(room, spare)
		shot["duration_seconds"] = float(shot["duration_seconds"]) + given
		spare -= given
		if spare <= 1e-9:
			return


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
	take_count = story_take_count(total_seconds, reference_contexts)
	lines = [
		DIRECTOR_RULES.format(
			take_count=take_count,
			min_take=MIN_TAKE_SECONDS,
			max_take=MAX_TAKE_SECONDS,
		),
		"",
		f'Every reference you list must use usage_role "{reference_role}".',
		"",
		"STORY ARC",
		*(
			f"- Take {number} {beat}: {STORY_BEATS[beat]}"
			for number, beat in enumerate(story_beats(take_count), start=1)
		),
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
	a take that shows a person gets [character, place]; otherwise the described
	place fills both slots.
	"""
	roster = build_roster(reference_contexts)
	if not roster[CHARACTER] or not roster[PLACE]:
		return shots
	character_key = roster[CHARACTER][0]["reference_key"]
	places = roster[PLACE]
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
			# The model follows <Picture 1> most strongly; a second, different place
			# there replaced the described one, so both slots carry it.
			ordered = [best_place, best_place]
		shot["references"] = [{"reference_key": key, "usage_role": reference_role} for key in ordered]
		prompt = _clamp_picture_tags(prompt, len(ordered)).strip()
		if "no cuts" not in prompt.lower():
			# Without it the model often cuts between angles inside one take.
			prompt = f"{prompt} {TAKE_CONSTRAINTS}".strip()
		shot["generation_prompt"] = prompt
	return shots


def plan_problems(shots, take_count):
	"""Return what is wrong with a story plan, phrased as corrections for the planner."""
	shots = [shot for shot in shots or [] if isinstance(shot, dict)]
	problems = []
	if len(shots) < take_count:
		problems.append(f"You returned {len(shots)} takes; return exactly {take_count}.")
	prompts = [" ".join(str(shot.get("generation_prompt") or "").lower().split()) for shot in shots]
	if len(set(prompts)) < len(prompts):
		problems.append("Several takes have the same generation_prompt; write each one for its own beat and place.")
	places = [
		str(((shot.get("references") or [{}])[-1] or {}).get("reference_key") or "")
		for shot in shots
	]
	overused = sorted({key for key in places if key and places.count(key) > 2})
	if overused:
		problems.append(f"Place {', '.join(overused)} is used more than twice; give those takes other places.")
	return problems


def _clamp_picture_tags(prompt, reference_count):
	"""Point tags beyond the images actually sent (e.g. a planner's <Picture 4>) at the last one."""
	return PICTURE_TAG_PATTERN.sub(
		lambda match: f"<Picture {min(max(int(match.group(1)), 1), reference_count)}>", prompt
	)


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
		name = " ".join(part for part in (context.get("label"), context.get("asset_name")) if part).strip()
		# A bare file name such as "3" says nothing about the picture; say so, so the
		# planner does not guess what the place looks like.
		description = name if WORD_PATTERN.search(name.lower()) else "(no visual description available)"
	if isinstance(analysis.get("outfit"), str) and analysis["outfit"].strip():
		description += f"; outfit: {analysis['outfit'].strip()}"
	return f"- key={context['reference_key']}: {description[:320]}"

