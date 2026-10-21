"""Model-independent shot grammar; actions remain in the existing scene contract."""

STAGES = {
	"establish",
	"approach",
	"grip",
	"extract",
	"present",
	"unfold",
	"inspect",
	"detail",
	"feel",
	"hero",
}
FRAMINGS = {"wide", "full", "medium", "medium_close_up", "close_up", "extreme_close_up"}
ANGLES = {"eye_level", "low_angle", "high_angle", "overhead", "oblique", "over_shoulder"}
MOTIONS = {"stationary", "locomotion", "manipulation"}

PLANNING_RULES = """
- Optional motion_plan.shot_structure describes cinematography independently of the video model:
  {"stage":"extract","framing":"close_up","angle":"high_angle",
   "subject_motion":"manipulation","keep_visible":["actor","product","container"]}.
  stage is establish|approach|grip|extract|present|unfold|inspect|detail|feel|hero;
  framing is wide|full|medium|medium_close_up|close_up|extreme_close_up;
  angle is eye_level|low_angle|high_angle|overhead|oblique|over_shoulder;
  subject_motion is stationary|locomotion|manipulation. keep_visible lists declared scene-contract entity IDs.
  Describe only the authored action. Grip precedes extraction; a product clears its opening before placement;
  support remains until a hand visibly takes its weight. Place the item before releasing the grip.
  Do not invent a box, lid, hinge, hand, tag, tool or packaging layer from the word 'unboxing'.
  Stage describes the dominant narrative job, not the first incidental hand gesture. Establish introduces
  geography; present/hero shows the product; feel shows a reaction. Holding an object during presentation
  does not make the shot a grip demonstration. Grip/extract/unfold/detail describe the interaction being shown.
  Use separate shots for distinct interactions, framing changes and locations. Precision manipulation uses
  locked coverage; broader presentation follows the shared stage grammar. Camera movement never substitutes
  for subject action or hides contact.
  New keyframe framing follows this structure; an approved first image keeps its actual composition.
"""


def authored_coverage(beat):
	"""Typed optional workbook fields override inference, never the supplied pixels."""
	result = {}
	for column, field, choices in [
		("shot_framing", "framing", FRAMINGS),
		("shot_angle", "angle", ANGLES),
		("narrative_stage", "stage", STAGES),
	]:
		value = str(beat.get(column) or "").strip()
		if value:
			if value not in choices:
				raise ValueError("Unsupported authored " + column + ": " + value)
			result[field] = value
	return result


def shot_structure(value, contract=None):
	if value is None:
		return None
	fields = {"stage", "framing", "angle", "subject_motion", "keep_visible"}
	if not isinstance(value, dict) or set(value) != fields:
		raise ValueError("Shot structure requires stage, framing, angle, subject_motion and keep_visible.")
	for name, options in [
		("stage", STAGES),
		("framing", FRAMINGS),
		("angle", ANGLES),
		("subject_motion", MOTIONS),
	]:
		if not isinstance(value[name], str) or value[name] not in options:
			raise ValueError("Unsupported shot structure " + name + ".")
	identifiers = value["keep_visible"]
	if (
		not isinstance(identifiers, list)
		or len(identifiers) > 12
		or any(not isinstance(i, str) or not i or len(i) > 80 for i in identifiers)
		or len(set(identifiers)) != len(identifiers)
	):
		raise ValueError("keep_visible requires unique declared entity IDs.")
	if contract is not None:
		known = {e["id"] for e in contract.get("entities", [])}
		if set(identifiers) - known:
			raise ValueError("Camera visibility targets must be declared scene entities.")
	elif identifiers:
		raise ValueError("Camera visibility targets require a scene contract.")
	return dict(value, keep_visible=list(identifiers))


def structure_for(shot):
	import json

	plan = shot.get("motion_plan_json") or {}
	if isinstance(plan, str):
		plan = json.loads(plan)
	return shot_structure(plan.get("shot_structure"), plan.get("scene_contract"))


def reference_requirements(value):
	if value is None:
		return []
	if not isinstance(value, list) or len(value) > 24:
		raise ValueError("Required references must be a list of at most 24 key/role pairs.")
	seen = set()
	for row in value:
		if (
			not isinstance(row, dict)
			or set(row) != {"key", "role"}
			or not isinstance(row["key"], str)
			or not row["key"]
			or len(row["key"]) > 100
			or row["role"] not in {"Person", "Character", "Product", "Environment", "Logo", "General"}
			or row["key"] in seen
		):
			raise ValueError("Required references need unique keys and supported roles.")
		seen.add(row["key"])
	return [dict(row) for row in value]


def require_scene_references(snapshot, scene):
	import json

	plan = scene.get("motion_plan_json") or {}
	if isinstance(plan, str):
		plan = json.loads(plan)
	available = {r.get("reference_key"): r for r in snapshot.get("references") or []}
	bound = {
		(r.get("asset_version"), str(r.get("reference_role") or "").casefold())
		for r in scene.get("references") or []
	}
	missing = []
	for need in reference_requirements(plan.get("required_references")):
		ref = available.get(need["key"])
		if (
			not ref
			or str(ref.get("reference_role") or "").casefold() != need["role"].casefold()
			or (ref.get("asset_version"), need["role"].casefold()) not in bound
		):
			missing.append(need["key"])
	if missing:
		raise ValueError("Missing required scene reference bindings: " + ", ".join(missing))


def framing_text(structure):
	return structure["angle"].replace("_", "-") + " " + structure["framing"].replace("_", "-")


def visibility_instruction(structure, contract):
	labels = {e["id"]: e["label"] for e in (contract or {}).get("entities", [])}
	targets = [labels[i] for i in structure["keep_visible"]]
	if not targets:
		return ""
	return (
		"Preserve the visible working area for "
		+ ", ".join(targets)
		+ ". Keep contact points and the container opening readable; natural hand occlusion is allowed. "
		"Do not crop away the action to simulate progress or create an extra copy during handling."
	)
