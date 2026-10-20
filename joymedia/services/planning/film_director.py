"""Cinematic planning rules for character + location films.

A "story film" is a project whose references contain at least one character
(talent) image and at least one place image. It is planned as a few long,
continuous takes rendered from the character and the specific locations used in
each take. A take can carry adjacent locations when its action transitions between
them.
"""

import math
import re
import unicodedata

import frappe

from joymedia.services.planning.director_rules import (
	CLOSING_DIRECTION,
	DIRECTOR_RULES,
	FEW_SHOT_EXAMPLE,
	PRODUCT_DIRECTOR_RULES,
	PRODUCT_FEW_SHOT_EXAMPLE,
	STORY_BEATS,
)
from joymedia.services.scene.contract import PLANNING_RULES

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
PRODUCT_BRIEF_PATTERN = re.compile(
	r"\b(advertis|promot|market|showcase|product|plate|dish|object|sell)\b|"
	r"qu[aả]ng\s*c[aá]o|gi[oớ]i\s*thi[eệ]u|c[aá]i\s*đĩa",
	re.I,
)

PERSON_PATTERN = re.compile(
	r"\b(she|her|hers|he|his|him|woman|man|girl|boy|person|characters?|couple|family)\b|\b(?:a|the|female|male|fashion)\s+model\b",
	re.I,
)
WORD_PATTERN = re.compile(r"[a-z]+")
PICTURE_TAG_PATTERN = re.compile(r"<Picture\s*(\d+)>", re.I)
TAKE_CONSTRAINTS = (
	"One continuous shot with no cuts, photorealistic, smooth stabilized motion, no added text or invented logos, "
	"no deformation."
)

MIN_TAKE_SECONDS = 5
# Default single-render duration used by the storyboard planner. Workflow capacity
# is enforced later by the generic segment planner, not encoded in creative rules.
MIN_RENDER_SECONDS = 5
# Each storyboard scene is planned as one render unless its workflow declares continuation.
MAX_TAKE_SECONDS = MIN_RENDER_SECONDS
MAX_TAKES = 12


def name_story_beats(shots):
	"""Set each take's beat from its position in the story arc, keeping the planner's title.

	The planner sometimes translates or invents the beat word ("Biến thể 1: …"), which
	loses which take is the climax.
	"""
	for shot, beat in zip(shots, story_beats(len(shots)), strict=False):
		name = str(shot.get("shot_name") or "").strip()
		title = name.split(":", 1)[1].strip() if ":" in name else name
		shot["shot_name"] = f"{beat}: {title}" if title else beat
	return shots


def close_the_film(shots):
	"""Make the last shot end the film; returns the shots."""
	if shots and isinstance(shots[-1], dict):
		last_shot = shots[-1]
		last_shot["handoff_type"] = "ending"
		prompt = str(last_shot.get("generation_prompt") or "").strip()
		if prompt and CLOSING_DIRECTION not in prompt:
			last_shot["generation_prompt"] = f"{prompt} {CLOSING_DIRECTION}"
		end_state = str(last_shot.get("end_state") or "").strip()
		if not end_state:
			last_shot["end_state"] = "A composed final frame, with all subject and camera movement settled."
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
	for chosen, choices in (
		(role, (CHARACTER_ROLES, PLACE_ROLES, PRODUCT_ROLES)),
		(category, (CHARACTER_CATEGORIES, PLACE_CATEGORIES, PRODUCT_CATEGORIES)),
	):
		for kind_of_reference, values in zip((CHARACTER, PLACE, PRODUCT), choices, strict=False):
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
	for shot, length in zip(shots, lengths(upper), strict=False):
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


def infer_product_reference_contexts(reference_contexts, video_idea):
	"""Classify one non-person image as the product when the brief is explicit.

	Image analysis is useful context, but a failed analysis must not turn a clear
	product brief into a location/story-film plan. The explicit brief is the
	safe fallback; only an unambiguous character + one other image is promoted.
	"""
	if not PRODUCT_BRIEF_PATTERN.search(str(video_idea or "")):
		return reference_contexts
	roster = build_roster(reference_contexts)
	if not roster[CHARACTER] or roster[PRODUCT] or len(roster[OTHER]) != 1:
		return reference_contexts
	product_key = roster[OTHER][0].get("reference_key")
	return [
		{**context, "reference_role": "Product"} if context.get("reference_key") == product_key else context
		for context in reference_contexts
	]


def _ascii_text(value):
	text = unicodedata.normalize("NFKD", str(value or ""))
	text = "".join(char for char in text if not unicodedata.combining(char))
	return text.replace("đ", "d").replace("Đ", "d").lower()


def _has_vietnamese(value):
	return bool(re.search(r"[\u00C0-\u024F]", str(value or "")))


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
		PLANNING_RULES,
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
			take_count=take_count,
			min_take=MIN_TAKE_SECONDS,
			max_take=MAX_TAKE_SECONDS,
			settings=settings,
		),
		PLANNING_RULES,
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
		*(_roster_line(context, product=True) for context in roster[PRODUCT]),
	]
	if roster[PLACE]:
		lines.append("PLACES")
		lines.extend(_roster_line(context) for context in roster[PLACE])
	lines.extend(["", PRODUCT_FEW_SHOT_EXAMPLE])
	return "\n".join(lines)


def normalize_story_references(shots, reference_contexts, reference_role, reference_roles=None):
	"""Assign ordered, purposeful references without discarding multi-place shots.

	For a tagged tour of places, selected areas are traversed in order. Extra scenes
	become bridge scenes with two adjacent areas, so every selected area is used.
	Every selected character remains in the reference assignment unless the planner
	explicitly narrows the cast; choosing the first roster entry silently discarded
	important cast members and made the result depend on upload order.
	"""
	roster = build_roster(reference_contexts)
	reference_roles = reference_roles or {}
	if roster[CHARACTER] and roster[PRODUCT]:
		return _normalize_product_references(shots, roster, reference_role, reference_roles)
	if not roster[CHARACTER] or not roster[PLACE]:
		return shots
	character_keys = [item["reference_key"] for item in roster[CHARACTER]]
	character_role = reference_roles.get(CHARACTER, reference_role)
	place_role = reference_roles.get(PLACE, reference_role)
	places = roster[PLACE]
	places_have_descriptions = any(
		str((place.get("analysis") or {}).get("description") or place.get("label") or "").strip()
		for place in places
	)
	place_tour = any(str(place.get("reference_role") or "").lower() == "environment" for place in places)
	for index, shot in enumerate(shots):
		if not isinstance(shot, dict):
			continue
		prompt = str(shot.get("generation_prompt") or "")
		listed = [
			str((reference or {}).get("reference_key") or "").strip()
			for reference in shot.get("references") or []
		]
		listed_characters = [key for key in listed if key in character_keys]
		characters = list(dict.fromkeys(listed_characters or character_keys))
		candidates = [context for context in places if context["reference_key"] in listed] or places
		listed_places = [key for key in listed if any(place["reference_key"] == key for place in places)]
		if place_tour:
			listed_places = _tour_places(index, len(shots), places, listed_places)
		else:
			# Preserve the mature single-location story-film behavior outside a
			# tagged tour of places. Multi-reference composition is intentionally
			# introduced only where the selected area sequence makes it meaningful.
			listed_places = []
		best_place = (
			_best_matching_place(prompt, candidates)
			if places_have_descriptions
			else places[index % len(places)]["reference_key"]
		)
		if PERSON_PATTERN.search(prompt):
			ordered = [*characters, *(listed_places or [best_place])]
		else:
			# The model follows <Picture 1> most strongly; a second, different place
			# there replaced the described one, so both slots carry it.
			ordered = [best_place, best_place]
		shot["references"] = [
			{"reference_key": key, "usage_role": character_role if key in character_keys else place_role}
			for key in ordered
		]
		prompt = _clamp_picture_tags(prompt, len(ordered)).strip()
		if "no cuts" not in prompt.lower():
			# Without it the model often cuts between angles inside one take.
			prompt = f"{prompt} {TAKE_CONSTRAINTS}".strip()
		shot["generation_prompt"] = prompt
	return shots


def _tour_places(index, shot_count, places, explicit_keys):
	"""Return one route segment for a tour of places, retaining explicit selections.

	When the film has more scenes than areas, fractional route positions naturally
	create adjacent-area bridge scenes. When it has fewer scenes, each scene carries
	the contiguous area range it must cover. This avoids silently dropping selected
	areas while keeping references ordered and bounded by the shot's purpose.
	"""
	# A planner can explicitly request a multi-area transition. A lone area from
	# the old two-reference prompt is not a reason to discard the rest of a tagged
	# tour of places, so it follows the deterministic route below.
	if len(explicit_keys) > 1:
		return list(dict.fromkeys(explicit_keys))
	keys = [place["reference_key"] for place in places]
	if not keys:
		return []
	if shot_count == len(keys):
		return [keys[min(index, len(keys) - 1)]]
	if shot_count > len(keys):
		position = index * (len(keys) - 1) / max(shot_count - 1, 1)
		start, end = math.floor(position), math.ceil(position)
		return list(dict.fromkeys(keys[start : end + 1]))
	start = math.floor(index * len(keys) / shot_count)
	end = math.ceil((index + 1) * len(keys) / shot_count)
	return keys[start : max(start + 1, end)]


def enforce_requested_product_presentation(shots, video_idea, reference_contexts):
	"""Keep explicit product-advertising briefs from degrading into walk-up scenes."""
	if not is_product_film(reference_contexts):
		return shots
	idea = str(video_idea or "").lower()
	if not re.search(
		r"quảng cáo|quang cao|giới thiệu|gioi thieu|promot|advertis|market|showcase|present", idea
	):
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


def explicit_product_brief_anchor(video_idea):
	"""Return a deterministic English anchor for an unambiguous product brief."""
	idea = str(video_idea or "").lower()
	advertising = re.search(
		r"quảng cáo|quang cao|giới thiệu|gioi thieu|promot|advertis|market|showcase", idea
	)
	plate = re.search(r"cái\s*đĩa|cai\s*dia|\bplate\b|\bdish\b", idea)
	if not advertising or not plate:
		return ""
	setting = product_brief_setting(video_idea)
	return (
		f"The woman advertises and presents the plate to camera in {setting}; "
		"the plate is the only advertised product, never cosmetics, food preparation, or another object."
	)


def product_brief_setting(video_idea):
	idea = str(video_idea or "").lower()
	if re.search(r"nhà hàng|nha hang|\brestaurant\b", idea):
		return "a luxurious restaurant"
	if re.search(r"khách sạn|khach san|\bhotel\b", idea):
		return "a luxurious five-star hotel"
	return "an elegant commercial setting"


def enforce_explicit_product_brief(shots, video_idea):
	"""Prevent a model plan from contradicting a clear product brief."""
	anchor = explicit_product_brief_anchor(video_idea)
	if not anchor:
		return shots
	for index, shot in enumerate(shots or [], start=1):
		if not isinstance(shot, dict):
			continue
		if index == 1:
			action = (
				"holds the plate securely with both hands and turns its decorated front toward the camera"
			)
		else:
			action = "keeps the plate presented to camera and gently tilts it to reveal its design"
		shot["generation_prompt"] = (
			f"The woman in the selected traditional ao dai {action}. {anchor} "
			"Use an elegant dining table, warm upscale lighting, and a shallow depth of field. "
			"One continuous shot with no cuts, photorealistic, smooth stabilized motion, no added text or invented logos, no deformation."
		)
		shot["image_prompt"] = (
			"The woman in the selected traditional ao dai holds the decorated plate toward camera "
			f"{product_brief_setting(video_idea)}, warm upscale commercial lighting, photorealistic starting frame."
		)
	return shots


def _normalize_product_references(shots, roster, reference_role, reference_roles=None):
	"""Keep every selected character/product identity instead of taking the first."""
	reference_roles = reference_roles or {}
	character_keys = [item["reference_key"] for item in roster[CHARACTER]]
	product_keys = [item["reference_key"] for item in roster[PRODUCT]]
	character_role = reference_roles.get(CHARACTER, reference_role)
	product_role = reference_roles.get(PRODUCT, reference_role)
	for shot in shots:
		if not isinstance(shot, dict):
			continue
		prompt = str(shot.get("generation_prompt") or "")
		# A relationship shot needs both bears (or all selected characters), while
		# an end-card/product hero may omit people.  Preserve a legacy duplicated
		# product only for the old single-product two-slot graph contract.
		ordered = (
			[*character_keys, *product_keys]
			if PERSON_PATTERN.search(prompt)
			else (product_keys * 2 if len(product_keys) == 1 else product_keys)
		)
		shot["references"] = [
			{"reference_key": key, "usage_role": character_role if key in character_keys else product_role}
			for key in ordered
		]
		prompt = _clamp_picture_tags(prompt, len(ordered)).strip()
		if "no cuts" not in prompt.lower():
			prompt = f"{prompt} {TAKE_CONSTRAINTS}".strip()
		shot["generation_prompt"] = prompt
	return shots


# Kinds of place a take's action can wrongly drift into (a balcony in a lobby photo).
PLACE_WORDS = (
	"balcony",
	"rooftop",
	"terrace",
	"pool",
	"lobby",
	"bedroom",
	"bathroom",
	"kitchen",
	"living room",
	"dining room",
	"garden",
	"beach",
	"gym",
	"playground",
	"spa",
	"restaurant",
	"bar",
	"office",
	"street",
	"park",
	"lake",
	"river",
	"forest",
	"mountain",
	"penthouse",
	"corridor",
	"hallway",
	"elevator",
	"courtyard",
	"library",
	"cafe",
	"studio",
	"boutique",
	"showroom",
	# Features a take invents inside a place just as often as whole places.
	"staircase",
	"stairs",
	"escalator",
	"fountain",
	"fireplace",
	"waterfall",
	"aquarium",
)


def place_text(context):
	"""Everything known about what a place reference shows."""
	analysis = context.get("analysis") if isinstance(context.get("analysis"), dict) else {}
	values = (
		context.get("reference_key"),
		context.get("label"),
		context.get("asset_name"),
		analysis.get("description"),
	)
	return " ".join(
		str(value).replace("_", " ").strip().lower()
		for value in values
		if re.search(r"[a-zA-Z]", str(value or ""))
	)


def invented_places(prompt, place_description):
	"""Kinds of place the prompt sets its action in that the place photo does not show."""
	prompt = str(prompt or "").lower()
	return [
		word
		for word in PLACE_WORDS
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
		problems.append(
			"Several takes have the same generation_prompt; write each one for its own beat and place."
		)
	place_keys = [
		str(((shot.get("references") or [{}])[-1] or {}).get("reference_key") or "") for shot in shots
	]
	overused = sorted({key for key in place_keys if key and place_keys.count(key) > 2})
	if overused:
		problems.append(
			f"Place {', '.join(overused)} is used more than twice; give those takes other places."
		)
	for number, (shot, key) in enumerate(zip(shots, place_keys, strict=False), start=1):
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
		return len(
			prompt_words & {word for word in WORD_PATTERN.findall(place_text(context)) if len(word) > 3}
		)

	return max(places, key=score)["reference_key"]


def reference_preamble(shot_reference_versions, project_references):
	"""Explain <Picture N> tags for one shot, from its ordered Asset Versions."""
	by_version = {
		reference.get("asset_version"): reference
		for reference in project_references or []
		if reference.get("asset_version")
	}
	parts = []
	locations = []
	for index, asset_version in enumerate(shot_reference_versions[:9], start=1):
		reference = by_version.get(asset_version) or {}
		label = str(reference.get("label") or "").strip()
		suffix = f" ({label})" if label else ""
		context = _asset_version_context(asset_version, reference)
		kind = classify_reference(context)
		if kind == CHARACTER:
			# Reference-to-Video can open on a reference photo as it is; the character's
			# photo must lend only the person, never its background.
			# Not every character is a person (a mascot has no hair or outfit), and the model draws the
			# pose it is given: say what the reference shows so the text and the picture agree.
			seen = _first_sentence((context.get("analysis") or {}).get("description"))
			seen = f" It shows {seen[0].lower()}{seen[1:]}" if seen else ""
			parts.append(
				f"<Picture {index}> is the main character{suffix}: keep its face, body and appearance "
				f"identical to the reference, but use only the character, never the background of that photo.{seen}"
			)
		elif kind == PLACE:
			locations.append(index)
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
	if locations:
		parts.append(f"The video opens directly in the location from <Picture {locations[0]}>.")
	if len(locations) > 1:
		parts.append(
			f"Make one motivated continuous transition from <Picture {locations[0]}> to <Picture {locations[1]}>; "
			"preserve both locations and do not invent an unrelated room."
		)
	if parts:
		parts.append(
			"References are independently framed; their pixel sizes do not establish physical scale. Follow the scene support surfaces and authored relative dimensions."
		)
	return " ".join(parts)


def _first_sentence(text, limit=220):
	"""The first sentence of an image description, ending with a full stop."""
	text = " ".join(str(text or "").split())
	sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0][:limit].rstrip(" .")
	return f"{sentence}." if sentence else ""


def _asset_version_context(asset_version, project_reference):
	"""Build the classify_reference input for an Asset Version from the database."""
	version = (
		frappe.db.get_value(
			"Asset Version", asset_version, ["media_asset", "analysis_status", "analysis_json"], as_dict=True
		)
		or frappe._dict()
	)
	asset = (
		frappe.db.get_value(
			"Media Asset", version.media_asset, ["media_type", "asset_category"], as_dict=True
		)
		if version.media_asset
		else None
	)
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
		seen = str(
			analysis.get("description") or context.get("label") or context.get("asset_name") or ""
		).strip()
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
