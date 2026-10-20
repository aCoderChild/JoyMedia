"""Family-role hints for any referenced character.

A role changes only relative height, build, posture and movement. Its identity
always remains defined by the selected reference, whether that subject is a
person, an illustrated character, or another kind of performer.
"""

from __future__ import annotations

import re
import unicodedata

# (key, English name, relative height, Vietnamese words, English words, how the role shows)
ROLES = (
	(
		"grandfather",
		"grandfather",
		0.95,
		("ông nội", "ông ngoại", "ông"),
		("grandfather", "grandpa", "granddad"),
		"an elderly full-grown adult, slightly stooped, slow and gentle movements, a kind wise expression",
	),
	(
		"grandmother",
		"grandmother",
		0.9,
		("bà nội", "bà ngoại", "bà"),
		("grandmother", "grandma", "granny"),
		"an elderly full-grown adult, a little shorter and rounder, slow and gentle movements, a warm smile",
	),
	(
		"father",
		"father",
		1.0,
		("bố", "cha", "ba"),
		("father", "dad", "daddy", "papa"),
		"a tall, sturdy broad-shouldered adult build, a protective, confident stance",
	),
	(
		"mother",
		"mother",
		1.0,
		("mẹ", "má"),
		("mother", "mom", "mum", "mommy", "mama"),
		"a full-grown adult, tall and soft-bodied, a caring, protective posture",
	),
	(
		"older_child",
		"older child",
		0.75,
		("anh trai", "chị gái"),
		("big brother", "big sister", "older brother", "older sister"),
		"clearly shorter than the adults, slimmer, lively movements",
	),
	(
		"child",
		"kid",
		0.55,
		("bé", "em bé", "nhí", "cháu", "con"),
		(
			"kid",
			"kids",
			"child",
			"children",
			"baby",
			"babies",
			"cub",
			"cubs",
			"son",
			"daughter",
			"toddler",
			"junior",
			"little",
		),
		"about half an adult's height, a small round body, a bigger head for its body, short arms and legs, "
		"playful childlike movements",
	),
)
COUNTS = "một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|các|những|mấy|mỗi|\\d+"
KEEP_DESIGN = "keeping exactly the reference subject's face, colours, markings, accessories and body design from its picture"


def _fold(text):
	return "".join(
		c for c in unicodedata.normalize("NFKD", str(text or "").casefold()) if not unicodedata.combining(c)
	).replace("đ", "d")


def _vietnamese(word):
	"""Where a Vietnamese role word may stand. "con" is a child only after a noun ("gấu con", a cub), not the
	classifier in "con gấu" ("a bear") or "ba con gấu" ("three bears"); "ba" is a father only after "gấu" or
	"mascot", as "ba" is also "three"."""
	if word == "con":
		return rf"(?<!\S)(?!(?:{COUNTS})\s)\w+\scon(?=\s|$|[,()])"
	if word == "ba":
		return r"(?<=gấu\s)ba\b|(?<=mascot\s)ba\b"
	return rf"(?:^|(?<=[\s(,-])){re.escape(word)}(?=$|[\s),-])"


# Words for the whole family or several of its members: every character with a family role is meant.
GROUP_WORDS = re.compile(
	r"\b(?:family|families|everyone|parents|the whole family)\b|(?:^|[\s(,-])(?:gia đình|cả nhà|mọi người|bố mẹ|ba mẹ|mẹ con|bố con|"
	r"ông bà|cả gia đình)(?=$|[\s),.-])",
	re.I,
)


def _matches(text, folded):
	"""(position, role) for every role word in the text."""
	found = []
	for key, _name, _size, vietnamese, english, _look in ROLES:
		for word in english:
			found += [(m.start(), key) for m in re.finditer(rf"\b{re.escape(word)}\b", folded)]
		for word in vietnamese:
			found += [(m.start(), key) for m in re.finditer(_vietnamese(word), text)]
	return found


def names_family(text):
	"""Whether the text speaks of the family as a group ("cả gia đình", "the whole family"), meaning all its members."""
	return bool(GROUP_WORDS.search(" ".join(str(text or "").casefold().split())))


def family_role(label):
	"""The family role a character's name gives it, or None; the first role word in the name wins ("gấu con của
	mẹ" is the cub)."""
	text = " ".join(str(label or "").casefold().split())
	found = _matches(text, _fold(text))
	return min(found)[1] if found else None


def role_size(label):
	"""Default relative height of a character from its role (1 when the name gives none)."""
	role = family_role(label)
	return next((size for key, _n, size, *_rest in ROLES if key == role), 1.0)


def role_name(label):
	"""The role's English name ("mother", "kid") or None."""
	role = family_role(label)
	return next((name for key, name, *_rest in ROLES if key == role), None)


def role_look(label):
	"""How the role changes proportions and posture without changing reference identity."""
	role = family_role(label)
	row = next((row for row in ROLES if row[0] == role), None)
	if not row:
		return ""
	article = "an" if row[1][0] in "aeiou" else "a"
	return f"with the build of {article} {row[1]}: {row[5]}, {KEEP_DESIGN}; no extra limbs or digits absent from the reference"


def role_words(display_name):
	"""The English words that mean a role-based display name, or ()."""
	return next(
		(
			english
			for _k, name, _s, _v, english, _l in ROLES
			if display_name in (f"the {name} character", f"the {name} mascot")
		),
		(),
	)
