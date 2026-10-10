"""Cinematic planning rules for character + location films.

A "story film" is a project whose references contain at least one character
(talent) image and at least one place image. It is planned as a few long,
continuous takes rendered by a workflow with two reference slots, where every take
receives the character as <Picture 1> and a location as <Picture 2>.
"""

import math
import re

import frappe


CHARACTER = "character"
PLACE = "place"
PRODUCT = "product"
OTHER = "other"

CHARACTER_ROLES = {"character"}
PLACE_ROLES = {"environment", "composition"}
PRODUCT_ROLES = {"product"}
CHARACTER_CATEGORIES = {"character"}
PLACE_CATEGORIES = {"background"}
PRODUCT_CATEGORIES = {"product"}

PERSON_PATTERN = re.compile(
	r"\b(she|her|hers|he|his|him|woman|man|girl|boy|person|character|couple|family)\b|\b(?:a|the|female|male|fashion)\s+model\b",
	re.I,
)
WORD_PATTERN = re.compile(r"[a-z]+")
PICTURE_TAG_PATTERN = re.compile(r"<Picture\s*(\d+)>", re.I)
TAKE_CONSTRAINTS = (
	"One continuous shot with no cuts, photorealistic, smooth stabilized motion, no text, no logos, "
	"no deformation."
)

MIN_TAKE_SECONDS = 5
# Default single-render duration used by the storyboard planner. Workflow capacity
# is enforced later by the generic segment planner, not encoded in creative rules.
MIN_RENDER_SECONDS = 5
# Each storyboard scene is planned as one render unless its workflow declares continuation.
MAX_TAKE_SECONDS = MIN_RENDER_SECONDS
MAX_TAKES = 12

DIRECTOR_RULES = """
You are the film director for JoyMedia commercials. Plan a short cinematic film
that follows the character through the supplied places, not a slideshow.

STRUCTURE
- Plan exactly {take_count} long continuous takes of {min_take}-{max_take} seconds each.
- Use a different place in each take, choosing the places that best tell the story;
  only the main place may appear twice (to open and to close the film).
- Each take is ONE unbroken camera shot in ONE place: no cuts, no montage, no
  second location inside the take.
- TIMING: use the opening moments (about 0-5%) to establish composition, carry out
  the main action in the first 85-90% of the take, then leave a natural handoff.
  Do not save the action for the end.
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

PRODUCT_DIRECTOR_RULES = """
You are the film director for JoyMedia commercials. Plan a short cinematic
commercial in which the character presents the product.

SOURCE OF TRUTH
- The VIDEO IDEA is the creative brief and has priority over default story beats,
  reference-photo backgrounds, asset filenames, and project metadata.
- Identify the requested subject, action, product, and setting from the VIDEO IDEA.
  Every take must visibly advance that requested action; do not substitute a related
  activity or invent a different product (for example, weaving/loom scenes for a
  product-advertising brief).
- When the brief says advertise, promote, or market the product, show the character
  actively presenting or demonstrating it to camera; merely entering, approaching,
  or standing beside it does not satisfy the brief.
- Reference images establish identity and product appearance, not an unrelated plot.
  If a product's visual description is unavailable, call it only "the product from
  <Picture 2>" and do not guess its material, purpose, or depicted scene.

THE PRODUCT
- The product in <Picture 2> is an OBJECT: the character holds, shows, uses, wears or
  admires it. It is never the setting and never a place to walk into, even when the
  product's picture shows a scene (a painting, a print, a decorated plate or a package
  can depict a landscape: it is still an object).
- Keep the product's exact shape, size, colours, patterns and details in every take,
  and keep it clearly visible: the film makes the product stand out.

STRUCTURE
- Plan exactly {take_count} long continuous takes of {min_take}-{max_take} seconds each.
- Each take is ONE unbroken camera shot in ONE setting: no cuts, no montage.
- TIMING: use the opening moments (about 0-5%) to establish composition, carry out
  the main action in the first 85-90% of the take, then leave a natural handoff.
  Do not save the action for the end.
- The character appears in every take except product hero takes. Include at least one
  hero take of the product alone (close-up, slow orbit or push-in on its details).
- Follow the STORY ARC below: each take plays its beat, in order. The CLIMAX shows the
  product at its best (the character revealing or using it, the boldest camera move).
- Adapt each beat to the VIDEO IDEA. The arc is only pacing guidance and must never
  change the requested action, product, or setting into a different concept.
- SETTINGS: {settings}
- The character keeps the outfit shown in <Picture 1> unless the VIDEO IDEA asks
  for a change. Vary performance and camera move between takes; never repeat an action.
- Match the look (light, colour grade, mood) to the VIDEO IDEA and GLOBAL INSTRUCTIONS
  and keep one consistent colour grade across all takes.
- shot_name is "<BEAT>: <short title>". Keep the BEAT word in English; write the short
  title in the language of the VIDEO IDEA.

EVERY generation_prompt (English, 60-110 words) states, in this order:
1. The person from <Picture 1>: their outfit and what they do with the product.
   If the VIDEO IDEA asks for promotion, explicitly show them holding or presenting
   the product to camera. Keep their face, hair and body identical to <Picture 1>.
2. The product from <Picture 2>: where it is (in their hands, on a table...) and its
   exact look. Keep its shape, colours and details identical to <Picture 2>.
3. The setting, in words.
4. One clear camera move, then light, grade and depth of field.
5. The constraints: one continuous shot with no cuts, photorealistic, smooth stabilized
   motion, no text, no logos, no extra people, no deformation.

REFERENCES
- Every take lists exactly two references: first the character key, then the product
  key. A product hero take lists the product key twice.
- Use only the supplied keys. In the prompt the character is always <Picture 1> and
  the product is always <Picture 2> (in a hero take, <Picture 1> and <Picture 2>
  are both the product).
""".strip()

PRODUCT_FEW_SHOT_EXAMPLE = (
	"generation_prompt TEMPLATE (fill every [ ] for its own beat; never reuse wording between "
	"takes): The person from <Picture 1>, in [outfit from <Picture 1>], [what they do with the "
	"product in this beat]. The product from <Picture 2>, [where it is and its exact look], keeps "
	"its exact shape, colours and details. [The setting, in words]. Keep their face and hair "
	"identical to <Picture 1>. [One camera move]. [Light, grade and depth of field]. One continuous "
	"shot with no cuts, photorealistic, smooth stabilized motion, no text, no logos, no deformation."
)

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


def name_story_beats(shots):
	"""Set each take's beat from its position in the story arc, keeping the planner's title.

	The planner sometimes translates or invents the beat word ("Biến thể 1: …"), which
	loses which take is the climax.
	"""
	for shot, beat in zip(shots, story_beats(len(shots))):
		name = str(shot.get("shot_name") or "").strip()
		title = name.split(":", 1)[1].strip() if ":" in name else name
		shot["shot_name"] = f"{beat}: {title}" if title else beat
	return shots


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
	minimum = max(1, math.ceil(total / MAX_TAKE_SECONDS))
	if minimum > MAX_TAKES:
		frappe.throw(
			f"This project needs {minimum} scenes at the {MAX_TAKE_SECONDS:.1f}-second render limit; "
			"shorten the video or increase the storyboard scene limit."
		)
	maximum = max(minimum, min(MAX_TAKES, math.floor(total / MIN_TAKE_SECONDS)))
	return minimum, maximum


def story_take_count(total_seconds, reference_contexts):
	"""Return how many takes to plan: one per place, within the duration's renderable range."""
	minimum, maximum = take_count_range(total_seconds)
	total = max(float(total_seconds or 0), MIN_TAKE_SECONDS)
	renderable = max(minimum, math.ceil(total / MAX_TAKE_SECONDS))
	if is_product_film(reference_contexts):
		# No place per take: about one take per seven seconds of film.
		return max(minimum, min(maximum, renderable, round(total / 7)))
	places = len(build_roster(reference_contexts)[PLACE])
	return max(minimum, min(places, maximum, renderable))


def classify_reference(context):
	"""Return CHARACTER, PLACE, PRODUCT or OTHER for one project reference context.

	What a person chose wins: the reference's role, then the asset's category, and
	only then the image analysis, which judges by what a picture shows (a product
	that is a painting of a harbour looks like a place).
	"""
	if (context.get("media_type") or "Image") != "Image":
		return OTHER
	role = str(context.get("reference_role") or "").strip().lower()
	category = str(context.get("asset_category") or "").strip().lower()
	analysis = context.get("analysis") if isinstance(context.get("analysis"), dict) else {}
	kind = str(analysis.get("kind") or "").strip().lower()
	for chosen, choices in ((role, (CHARACTER_ROLES, PLACE_ROLES, PRODUCT_ROLES)), (category, (
		CHARACTER_CATEGORIES, PLACE_CATEGORIES, PRODUCT_CATEGORIES
	))):
		for kind_of_reference, values in zip((CHARACTER, PLACE, PRODUCT), choices):
			if chosen in values:
				return kind_of_reference
	return {"person": CHARACTER, "place": PLACE, "product": PRODUCT}.get(kind, OTHER)


def balance_take_durations(shots, total_seconds):
	"""Keep every take inside one workflow render while preserving the total.

	Takes keep their planned proportions where possible. When the total cannot give
	every take the minimum length, the shortest middle takes are dropped.
	"""
	total = float(total_seconds or 0)
	if not shots or total <= 0:
		return shots
	shots = list(shots)
	while len(shots) > 1 and len(shots) * MIN_RENDER_SECONDS > total:
		remove_index = (
			min(range(1, len(shots) - 1), key=lambda index: float(shots[index]["duration_seconds"]))
			if len(shots) > 2
			else 1
		)
		shots.pop(remove_index)
	minimum, _maximum = take_count_range(total)
	if len(shots) < minimum:
		# The planner normally supplies this many takes. Keep the configured render cap even
		# when a model response is short by splitting the longest supplied beat.
		while len(shots) < minimum:
			longest = max(shots, key=lambda shot: float(shot["duration_seconds"]))
			clone = dict(longest)
			clone["shot_name"] = f"{clone.get('shot_name') or 'SCENE'}: continuation beat"
			shots.append(clone)
	low = min(MIN_RENDER_SECONDS, total / len(shots))
	high = MAX_TAKE_SECONDS
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
	roster = {CHARACTER: [], PLACE: [], PRODUCT: [], OTHER: []}
	for context in reference_contexts or []:
		if not context.get("reference_key"):
			continue
		roster[classify_reference(context)].append(context)
	return roster


def is_story_film(reference_contexts):
	"""A character with places to move through, or with a product to present."""
	roster = build_roster(reference_contexts)
	return bool(roster[CHARACTER] and (roster[PLACE] or roster[PRODUCT]))


def is_product_film(reference_contexts):
	"""A character presenting a product: the product is the star, never the setting."""
	roster = build_roster(reference_contexts)
	return bool(roster[CHARACTER] and roster[PRODUCT])


def build_director_instruction(reference_contexts, reference_role, total_seconds, reference_roles=None):
	"""Return the planner instruction for a story film, including the reference roster."""
	roster = build_roster(reference_contexts)
	reference_roles = reference_roles or {}
	take_count = story_take_count(total_seconds, reference_contexts)
	if roster[PRODUCT]:
		return _product_director_instruction(roster, reference_role, take_count, reference_roles)
	character_role = reference_roles.get(CHARACTER, reference_role)
	place_role = reference_roles.get(PLACE, reference_role)
	lines = [
		DIRECTOR_RULES.format(
			take_count=take_count,
			min_take=MIN_TAKE_SECONDS,
			max_take=MAX_TAKE_SECONDS,
		),
		"",
		f'Use usage_role "{character_role}" for character references and "{place_role}" for place references.',
		"",
		"STORY ARC",
		*(
			f"- Take {number} {beat}: {STORY_BEATS[beat]}"
			for number, beat in enumerate(story_beats(take_count), start=1)
		),
		"",
		"CHARACTER",
	]
	lines.extend(_roster_line(context, person=True) for context in roster[CHARACTER])
	lines.append("PLACES")
	lines.extend(_roster_line(context) for context in roster[PLACE])
	lines.extend(["", FEW_SHOT_EXAMPLE])
	return "\n".join(lines)


def _product_director_instruction(roster, reference_role, take_count, reference_roles=None):
	reference_roles = reference_roles or {}
	character_role = reference_roles.get(CHARACTER, reference_role)
	product_role = reference_roles.get(PRODUCT, reference_role)
	if roster[PLACE]:
		settings = (
			"set the takes in the places listed under PLACES, described in words (their pictures "
			"are not sent with the product takes); the same place may host several takes."
		)
	else:
		settings = (
			"choose settings that suit the product and the VIDEO IDEA (for example a bright minimal "
			"studio or a warm, tasteful living space) and keep them consistent across the film."
		)
	lines = [
		PRODUCT_DIRECTOR_RULES.format(
			take_count=take_count, min_take=MIN_TAKE_SECONDS, max_take=MAX_TAKE_SECONDS, settings=settings,
		),
		"",
		f'Use usage_role "{character_role}" for character references and "{product_role}" for product references.',
		"",
		"STORY ARC",
		*(
			f"- Take {number} {beat}: {STORY_BEATS[beat]}"
			for number, beat in enumerate(story_beats(take_count), start=1)
		),
		"",
		"CHARACTER",
		*(_roster_line(context, person=True) for context in roster[CHARACTER]),
		"PRODUCT",
		*(_roster_line(context, product=True) for context in roster[PRODUCT][:1]),
	]
	if roster[PLACE]:
		lines.append("PLACES")
		lines.extend(_roster_line(context) for context in roster[PLACE])
	lines.extend(["", PRODUCT_FEW_SHOT_EXAMPLE])
	return "\n".join(lines)


def normalize_story_references(shots, reference_contexts, reference_role, reference_roles=None):
	"""Make every shot reference exactly two images, in <Picture 1>/<Picture 2> order.

	The order is load-bearing: the first reference is bound to <Picture 1> and the
	second to <Picture 2> by the Reference-to-Video workflow bindings. The planner's
	prompt text decides the order, because models often omit or reorder keys:
	a take that shows a person gets [character, place]; otherwise the described
	place fills both slots.
	"""
	roster = build_roster(reference_contexts)
	reference_roles = reference_roles or {}
	if roster[CHARACTER] and roster[PRODUCT]:
		return _normalize_product_references(shots, roster, reference_role, reference_roles)
	if not roster[CHARACTER] or not roster[PLACE]:
		return shots
	character_key = roster[CHARACTER][0]["reference_key"]
	character_role = reference_roles.get(CHARACTER, reference_role)
	place_role = reference_roles.get(PLACE, reference_role)
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
		shot["references"] = [
			{"reference_key": key, "usage_role": character_role if index == 0 and PERSON_PATTERN.search(prompt) else place_role}
			for index, key in enumerate(ordered)
		]
		prompt = _clamp_picture_tags(prompt, len(ordered)).strip()
		if "no cuts" not in prompt.lower():
			# Without it the model often cuts between angles inside one take.
			prompt = f"{prompt} {TAKE_CONSTRAINTS}".strip()
		shot["generation_prompt"] = prompt
	return shots


def enforce_requested_product_presentation(shots, video_idea, reference_contexts):
	"""Keep explicit product-advertising briefs from degrading into walk-up scenes."""
	if not is_product_film(reference_contexts):
		return shots
	idea = str(video_idea or "").lower()
	if not re.search(r"quảng cáo|quang cao|giới thiệu|gioi thieu|promot|advertis|market|showcase|present", idea):
		return shots
	for shot in shots or []:
		if not isinstance(shot, dict):
			continue
		prompt = str(shot.get("generation_prompt") or "").strip()
		if re.search(r"\b(hold|holding|present|presenting|demonstrat|show(?:ing)?)\b", prompt, re.I):
			continue
		if int(shot.get("shot_number") or 1) == 1:
			action = (
				"The model actively promotes the product, holding it securely with both hands and "
				"turning its decorated front toward the camera so the viewer can clearly see it."
			)
		else:
			action = (
				"Continuing seamlessly, the model keeps the product presented to camera and gently "
				"tilts it to reveal its design while addressing the viewer."
			)
		shot["generation_prompt"] = f"{prompt} {action}".strip()
	return shots


def _normalize_product_references(shots, roster, reference_role, reference_roles=None):
	"""[character, product] for takes with the person, [product, product] for hero takes."""
	reference_roles = reference_roles or {}
	character_key = roster[CHARACTER][0]["reference_key"]
	product_key = roster[PRODUCT][0]["reference_key"]
	character_role = reference_roles.get(CHARACTER, reference_role)
	product_role = reference_roles.get(PRODUCT, reference_role)
	for shot in shots:
		if not isinstance(shot, dict):
			continue
		prompt = str(shot.get("generation_prompt") or "")
		ordered = [character_key, product_key] if PERSON_PATTERN.search(prompt) else [product_key, product_key]
		shot["references"] = [
			{"reference_key": key, "usage_role": character_role if key == character_key else product_role}
			for key in ordered
		]
		prompt = _clamp_picture_tags(prompt, len(ordered)).strip()
		if "no cuts" not in prompt.lower():
			prompt = f"{prompt} {TAKE_CONSTRAINTS}".strip()
		shot["generation_prompt"] = prompt
	return shots


# Kinds of place a take's action can wrongly drift into (a balcony in a lobby photo).
PLACE_WORDS = (
	"balcony", "rooftop", "terrace", "pool", "lobby", "bedroom", "bathroom", "kitchen", "living room",
	"dining room", "garden", "beach", "gym", "playground", "spa", "restaurant", "bar", "office",
	"street", "park", "lake", "river", "forest", "mountain", "penthouse", "corridor", "hallway",
	"elevator", "courtyard", "library", "cafe", "studio", "boutique", "showroom",
	# Features a take invents inside a place just as often as whole places.
	"staircase", "stairs", "escalator", "fountain", "fireplace", "waterfall", "aquarium",
)


def place_text(context):
	"""Everything known about what a place reference shows."""
	analysis = context.get("analysis") if isinstance(context.get("analysis"), dict) else {}
	return " ".join(
		str(value or "")
		for value in (context.get("reference_key"), context.get("label"), context.get("asset_name"), analysis.get("description"))
	).replace("_", " ").lower()


def invented_places(prompt, place_description):
	"""Kinds of place the prompt sets its action in that the place photo does not show."""
	prompt = str(prompt or "").lower()
	return [
		word for word in PLACE_WORDS
		if re.search(rf"\b{word}s?\b", prompt) and not re.search(rf"\b{word}", place_description)
	]


def plan_problems(shots, take_count, places=None):
	"""Return what is wrong with a story plan, phrased as corrections for the planner.

	places maps a place reference_key to place_text(); with it, takes whose action
	drifts into a place their photo does not show are reported.
	"""
	shots = [shot for shot in shots or [] if isinstance(shot, dict)]
	problems = []
	if len(shots) < take_count:
		problems.append(f"You returned {len(shots)} takes; return exactly {take_count}.")
	prompts = [" ".join(str(shot.get("generation_prompt") or "").lower().split()) for shot in shots]
	if len(set(prompts)) < len(prompts):
		problems.append("Several takes have the same generation_prompt; write each one for its own beat and place.")
	place_keys = [
		str(((shot.get("references") or [{}])[-1] or {}).get("reference_key") or "")
		for shot in shots
	]
	overused = sorted({key for key in place_keys if key and place_keys.count(key) > 2})
	if overused:
		problems.append(f"Place {', '.join(overused)} is used more than twice; give those takes other places.")
	for number, (shot, key) in enumerate(zip(shots, place_keys), start=1):
		description = (places or {}).get(key)
		invented = invented_places(shot.get("generation_prompt"), description) if description else []
		if invented:
			problems.append(
				f"Take {number} sets its action in a {' / '.join(invented)}, but its place {key} shows: "
				f"{description[:160]}. Keep the whole take inside what that place shows."
			)
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
		return len(prompt_words & {word for word in WORD_PATTERN.findall(place_text(context)) if len(word) > 3})

	return max(places, key=score)["reference_key"]


def reference_preamble(shot_reference_versions, project_references):
	"""Explain <Picture N> tags for one shot, from its ordered Asset Versions."""
	by_version = {
		reference.get("asset_version"): reference
		for reference in project_references or []
		if reference.get("asset_version")
	}
	parts = []
	location = None
	for index, asset_version in enumerate(shot_reference_versions[:9], start=1):
		reference = by_version.get(asset_version) or {}
		label = str(reference.get("label") or "").strip()
		suffix = f" ({label})" if label else ""
		context = _asset_version_context(asset_version, reference)
		kind = classify_reference(context)
		if kind == CHARACTER:
			# Reference-to-Video can open on a reference photo as it is; the character's
			# photo must lend only the person, never its background.
			parts.append(
				f"<Picture {index}> is the main character{suffix}: keep the face, hair, body and outfit "
				"identical, but use only the person, never the background of that photo."
			)
		elif kind == PLACE:
			location = location or index
			# Spell the place out: when a take's own text barely describes where it is,
			# the model drifts to the setting of the character's photo instead.
			seen = _first_sentence((context.get("analysis") or {}).get("description"))
			seen = f" It shows {seen[0].lower()}{seen[1:]}" if seen else ""
			parts.append(
				f"<Picture {index}> is the location{suffix}: keep its architecture, layout and materials exactly.{seen}"
			)
		elif kind == PRODUCT:
			parts.append(
				f"<Picture {index}> is the product{suffix}: keep its exact shape, size, colours, patterns and "
				"details. It is an object in the scene, never the setting."
			)
		else:
			parts.append(
				f"<Picture {index}> is a reference subject{suffix}: keep its shape, colours and details exactly."
			)
	if location:
		parts.append(f"The video opens directly in the location from <Picture {location}>.")
	return " ".join(parts)


def _first_sentence(text, limit=220):
	"""The first sentence of an image description, ending with a full stop."""
	text = " ".join(str(text or "").split())
	sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0][:limit].rstrip(" .")
	return f"{sentence}." if sentence else ""


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


def _roster_line(context, person=False, product=False):
	analysis = context.get("analysis") if isinstance(context.get("analysis"), dict) else {}
	if product:
		# Say what it is before what it depicts: a product that is a painting of a
		# harbour must not become the harbour.
		seen = str(analysis.get("description") or context.get("label") or context.get("asset_name") or "").strip()
		return f"- key={context['reference_key']}: THE PRODUCT, an object (not a place); its picture: {seen[:300]}"
	outfit = str(analysis.get("outfit") or "").strip() if isinstance(analysis.get("outfit"), str) else ""
	if person and outfit:
		# Only the person's look: the background of their photo ("outdoors among lotus
		# flowers") is not a place, and the planner would paste it into every take.
		return f"- key={context['reference_key']}: a person; look and outfit: {outfit[:200]}"
	description = str(analysis.get("description") or "").strip()
	if not description:
		name = " ".join(part for part in (context.get("label"), context.get("asset_name")) if part).strip()
		# A bare file name such as "3" says nothing about the picture; say so, so the
		# planner does not guess what the place looks like.
		description = name if WORD_PATTERN.search(name.lower()) else "(no visual description available)"
	if isinstance(analysis.get("outfit"), str) and analysis["outfit"].strip():
		description += f"; outfit: {analysis['outfit'].strip()}"
	return f"- key={context['reference_key']}: {description[:320]}"
