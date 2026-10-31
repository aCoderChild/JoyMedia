"""Turn a classified scene failure into one targeted script change.

The batch used to answer a failed frame by redrawing it or by asking the writer
to rewrite the scene from free-text notes; the writer often reproduced the
failing choice. Following rule-level attribution (SAGE, arXiv:2608.17468), each
failure is attributed to the scene choice that causes it. Mechanical slips
(package words, printed sheets) are edited in code. Creative choices (pose,
support, framing) stay the writer's: the writer gets the attributed cause and
decides the new staging. Each change is remembered so it is never applied twice;
a repeat escalates to the existing writer rewrite instead.
"""

import re

from joymedia.services.planning.creative import MATERIAL, PACKAGE_PHRASE

# Evidence the checks already record (shot notes and failed attempt errors).
FAILURES = (
	("framing", ("Critical framing: full character body appears in a close",)),
	(
		"invented_package",
		(
			"unreferenced retail packages appear in a product-free shot",
			"actor holds an undeclared retail package",
		),
	),
	(
		"support",
		(
			"rests on a table or work surface instead of a seat or the floor",
			"actor's seat or floor contact contradicts the authored scene",
			# An unconfirmed opening is edited only when its scene has the table/floor conflict.
			"Automatic screening could not confirm it",
		),
	),
	("sheet_print", ("loose sheet carries no unauthored", "unauthored printed text, logo or illustration")),
	(
		"pack_compositing",
		(
			"Expected one unambiguous product; detected ",
			"Source product view changes its measured scene footprint",
			"advertised product camera angle conflicts",
			"character stands on the advertised product",
			"product retains a rectangular studio-background matte",
			"advertised product is not on its authored support",
		),
	),
)


def classify(evidence):
	"""Failure kinds named by a scene's recorded evidence."""
	return [kind for kind, markers in FAILURES if any(marker in evidence for marker in markers)]


def _material(scene):
	match = MATERIAL.search(" ".join(str(scene.get(k) or "") for k in ("visual_camera", "action")))
	return match.group().lower() if match else None


def _strip_packages(scene):
	for field in ("visual_camera", "action", "continuity_rules"):
		scene[field] = PACKAGE_PHRASE.sub("", str(scene.get(field) or ""))


# Pose, support and framing are the script's to decide: the writer gets the cause.
WRITER_NOTES = {
	"framing": (
		"This close framing was drawn three times as a full-body picture. Restage the scene so its framing "
		"and its opening agree: either a true detail of the paws and the material with no full body in the "
		"opening text, or a wider framing whose action reads at full body. Choose whichever serves the story."
	),
	"support": (
		"The picture model could not stage this opening as written (it seated the character on the table "
		"or could not show the stated support). State exactly what the character sits or stands on, and "
		"put the material where that pose can reach it. Choose the pose and support that serve the story."
	),
}


def writer_notes(failures, applied):
	"""Scene-repair notes for the creative failures not yet sent to the writer; updates ``applied``."""
	notes = []
	for number, kinds in sorted(failures.items()):
		for kind in kinds:
			key = f"{number}:{kind}"
			if kind in WRITER_NOTES and key not in applied:
				applied.add(key)
				notes.append({"scene": number, "text": WRITER_NOTES[kind]})
	return notes


def _edit(scene, kind):
	"""Apply one mechanical edit in place; False when it does not apply to this scene."""
	if kind in WRITER_NOTES or not scene.get("cast"):
		return False  # Product-only shots use the source photograph.
	if kind == "pack_compositing":
		if not scene.get("products"):
			return False
		scene["products"] = []
		_strip_packages(scene)
		return True
	material = _material(scene)
	if not material:
		return False
	if kind == "invented_package":
		_strip_packages(scene)
		# A positive inventory, not a list of objects to avoid: naming them primes them.
		scene["continuity_rules"] = (
			str(scene.get("continuity_rules") or "").rstrip()
			+ f" The {material} is the only loose object near the character, resting on its support."
		).strip()
		return True
	if kind == "sheet_print":
		text = str(scene.get("visual_camera") or "")
		if "unprinted" in text.lower():
			return False
		scene["visual_camera"] = re.sub(
			rf"\b{re.escape(material)}\b", f"plain, unprinted white {material}", text, count=1, flags=re.I
		)
		return True
	return False


def apply_edits(script, failures, applied):
	"""Edit each failing scene once per failure kind.

	``failures`` maps a 1-based scene number to its failure kinds; ``applied``
	holds "scene:kind" keys already used and is updated in place. Returns the
	1-based scene numbers that changed.
	"""
	scenes = script.get("scenes") or []
	changed = []
	for number, kinds in sorted(failures.items()):
		if not 0 < number <= len(scenes):
			continue
		for kind in kinds:
			key = f"{number}:{kind}"
			if key in applied:
				continue
			if _edit(scenes[number - 1], kind):
				applied.add(key)
				if number not in changed:
					changed.append(number)
	return changed
