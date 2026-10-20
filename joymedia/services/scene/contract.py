"""Bounded, provider-independent scene relationships shared by planning and review.

These are authored intentions, never measurements of generated footage. They live
inside the existing motion-plan snapshot so retries and workflow changes use the
same contract. No model, product, species, or node names belong here.
"""

import json
import math
import re

from joymedia.services.scene.structure import normalize_structure, structure_claims

RELATIONS = {
	"attached_to": "stays connected to",
	"flows_from": "originates only from",
	"supported_by": "remains supported by",
	"contacts": "makes visible contact with",
}

STAGING_RULES = """Physical staging:
- Establish the visible actor, objects, support surfaces and material source in the first frame.
- Name the owner of every acting body part. Keep its connection visible when framing permits it.
- Stage reachable contact: furniture and props must fit the actor's scale and opening pose.
- Preserve the reference subject's topology and body-part proportions when adapting its pose.
  Fit support height, seat depth, footrests and prop position to the subject; never lengthen
  a limb or invent joints so it can reach a floor or surface. A seated subject need not
  touch the floor unless the brief requires it. Distinguish a compact reference appendage
  from human anatomy; plausible occlusion does not authorize inventing hidden segments.
- Establish explicit relative dimensions for interacting objects at comparable depth. Reference
  image framing is not physical scale. A close-up product photo must not become an oversized prop.
- Describe cause, contact, then effect in that order. A material comes from its named source;
  contact with an actor does not turn that actor into its source.
- Specify the actual body-part morphology from the reference, not a human default.
- Preserve the authored cause and intention of an interaction; do not substitute a different action.
- Humans intentionally participating in the scene must use an explicit Person reference.
  A Product or Character reference never authorizes an extra human hand, helper or actor.
- Preserve material quantity and object state unless a visible authored event changes them.
  A container must not drain, refill or leak during an unrelated action. Show any transfer
  at its actual source boundary; preserve the established level when no transfer occurs.
- Deformation follows the established material and local contact: folds and wrinkles move near the applied force.
  Preserve overall dimensions and surface artwork unless an authored action physically changes them;
  releasing a grip settles naturally, without whole-object elastic pulsing or spring-like recoil.
- Keep support, contact and occlusion plausible for the actual objects in this scene.
  Add no unstated furniture, actors, anatomy, materials or actions. No object category implies
  a fixed number of parts, a support surface, a holder or a particular physical scale.
- Use one main interaction per continuous shot. If the requested sequence needs cuts or cannot
  fit its duration, report needs_editing; never silently omit a required action.
"""

PLANNING_RULES = (
	STAGING_RULES
	+ """
- motion_plan.scene_contract is optional when no physical interaction needs constraints.
  Start with {"version":1,"entities":[{"id":"subject","label":"the authored subject"}],"relations":[],"events":[]}.
  Populate only the entities, relationships and events established by this scene; no actor is required.
  Relationship rows use {"kind":"supported_by","subject":"declared subject ID","object":"declared support ID"}.
  Event rows use {"id":"cause","description":"the authored visible event","start":0,"end":1,"after":[]} only when an event is required.
  Declare every referenced entity, use unique IDs, and only assert relationships required by
  the beat. flows_from links a material to its source; attached_to links a part to its owner.
  supported_by and contacts link objects. Events use seconds within the shot; after lists
  earlier event IDs. Optional checks: [{"id":"shape","scope":"opening","claim":"visible staging constraint"},
  {"id":"action_identity","scope":"sequence","claim":"specific observable action requirement"}].
  Opening checks describe one still frame; sequence checks are invariants true throughout the clip.
  A state that applies only during an action uses {"id":"grip","scope":"event","event":"cause",
  "claim":"The visible hand maintains contact while carrying the item."}. The event must exist;
  its start/end bound this check. Do not require a grip after the authored release.
  Use checks for actual anatomy, object counts, support geometry and accidental versus intentional action.
  Optional proportions: [{"subject":"vessel","reference":"actor","axis":"height","min":0.12,"max":0.2}].
  These are authored physical dimension ratios, not measurements of pixels. Declare both entities,
  compare the same dimension, and use a plausible range at comparable depth. Use only when the
  beat or approved references establish relative scale; do not invent exact real-world dimensions.
  Optional structural data (only when established by the brief or approved reference):
  counts: [{"entity":"object","count":1,"visibility":"visible|occlusion_allowed"}],
  parts: [{"entity":"object","label":"authored part name","count":2,"visibility":"occlusion_allowed"}],
  properties: [{"entity":"object","name":"authored property","value":"required appearance or geometry"}].
  A part count of 0 explicitly forbids a reference-absent feature; never add an absent
  handle, appendage, joint or decorative part merely because its category often has one.
  These requirements apply to opening staging and sequence consistency. Hidden parts are not
  proof of missing parts. Counts describe physical objects, not people or scenes depicted on a surface.
  Never assume a product is packaging or animate its printed decoration as a separate scene.
  Do not add actors, materials, interactions or assertions absent from the beat.
- Preservation controls describe rendering, not extra visible objects. Never invent an actor
  for a product-only scene. motion_plan.camera_motion may be locked or moving when established.
  For a product-only shot with an explicitly stationary subject and locked camera, set
  camera_motion=locked and include motion=stationary properties for all physical entities,
  with events=[]. This permits a deterministic presentation of the prepared source frame.
  Do not list a camera as a physical entity. Never use that static contract for opening,
  turning, flowing, gesturing, changing shape, interacting, or moving/orbiting cameras;
  preserve the authored action and its events instead. Unknown motion is not stationary.
"""
)


def read_contract(plan, duration=None):
	"""Validate strictly; a malformed explicit contract must never silently disappear."""
	if isinstance(plan, str):
		plan = json.loads(plan) if plan.strip() else {}
	value = plan.get("scene_contract") if isinstance(plan, dict) else None
	if value is None:
		return None
	if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
		raise ValueError("Scene contract requires version 1.")
	unknown = set(value) - {
		"version",
		"entities",
		"relations",
		"events",
		"checks",
		"proportions",
		"counts",
		"parts",
		"properties",
	}
	if unknown:
		raise ValueError("Unsupported scene contract fields: " + ", ".join(sorted(unknown)))

	def rows(key, limit):
		items = value.get(key, [])
		if not isinstance(items, list) or len(items) > limit or any(not isinstance(r, dict) for r in items):
			raise ValueError(f"Scene contract {key} must contain at most {limit} objects.")
		return items

	def text(value, field):
		if not isinstance(value, str) or not value.strip() or len(value) > 240:
			raise ValueError(f"Scene contract {field} must be nonempty text of at most 240 characters.")
		return " ".join(value.split())

	def identifier(value):
		if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,47}", value):
			raise ValueError("Scene contract IDs must be short identifiers.")
		return value

	entities, events = {}, {}
	for row in rows("entities", 16):
		key = identifier(row.get("id"))
		if key in entities:
			raise ValueError("Scene contract entity IDs must be unique.")
		entities[key] = {"id": key, "label": text(row.get("label"), "label")}
	relations = []
	for row in rows("relations", 16):
		kind, subject, obj = row.get("kind"), row.get("subject"), row.get("object")
		if (
			not isinstance(kind, str)
			or kind not in RELATIONS
			or not isinstance(subject, str)
			or not isinstance(obj, str)
			or subject not in entities
			or obj not in entities
			or subject == obj
		):
			raise ValueError(
				"Scene contract relations require a known kind and two distinct declared entities."
			)
		relation = {"kind": kind, "subject": subject, "object": obj}
		if relation not in relations:
			relations.append(relation)
	proportions, pairs = [], set()
	for row in rows("proportions", 8):
		subject, reference, axis = row.get("subject"), row.get("reference"), row.get("axis")
		if (
			not isinstance(subject, str)
			or not isinstance(reference, str)
			or subject not in entities
			or reference not in entities
			or subject == reference
			or axis not in ("height", "width", "depth")
		):
			raise ValueError(
				"Proportions require two distinct declared entities and a height, width or depth axis."
			)
		low, high = row.get("min"), row.get("max")
		if any(type(v) not in (int, float) or not 0.01 <= v <= 100 for v in (low, high)) or low > high:
			raise ValueError(
				"Proportion bounds must be finite ratios between 0.01 and 100, ordered min to max."
			)
		pair = (*sorted((subject, reference)), axis)
		if pair in pairs:
			raise ValueError("Declare each proportion pair and axis only once, including inverse pairs.")
		pairs.add(pair)
		proportions.append(
			{"subject": subject, "reference": reference, "axis": axis, "min": low, "max": high}
		)
	owners = {}
	for row in relations:
		if row["kind"] == "attached_to":
			if row["subject"] in owners and owners[row["subject"]] != row["object"]:
				raise ValueError("An attached part cannot have two owners.")
			owners[row["subject"]] = row["object"]
	for key in owners:
		seen, current = set(), key
		while current in owners:
			if current in seen:
				raise ValueError("Scene contract ownership cannot be cyclic.")
			seen.add(current)
			current = owners[current]
	for row in rows("events", 8):
		key = identifier(row.get("id"))
		if key in events:
			raise ValueError("Scene contract event IDs must be unique.")
		start, end = row.get("start"), row.get("end")
		if (
			any(type(t) not in (int, float) or not math.isfinite(t) for t in (start, end))
			or not 0 <= start < end
			or (duration is not None and end > float(duration) + 0.01)
		):
			raise ValueError("Scene contract events require finite positive intervals within the shot.")
		after = row.get("after", [])
		if not isinstance(after, list) or len(after) > 8:
			raise ValueError("Scene contract event dependencies must be a bounded list.")
		events[key] = {
			"id": key,
			"description": text(row.get("description"), "description"),
			"start": start,
			"end": end,
			"after": [identifier(k) for k in after],
		}
	for row in events.values():
		for key in row["after"]:
			if key not in events or events[key]["end"] > row["start"]:
				raise ValueError("An event must follow the completion of its declared causes.")
	checks, ids = [], set()
	for row in rows("checks", 8):
		key = identifier(row.get("id"))
		if key in ids or row.get("scope") not in {"opening", "sequence", "event"}:
			raise ValueError("Scene checks need unique IDs and opening, sequence or event scope.")
		ids.add(key)
		check = {"id": key, "claim": text(row.get("claim"), "claim"), "scope": row["scope"]}
		if row["scope"] == "event":
			event_key = identifier(row.get("event"))
			if event_key not in events:
				raise ValueError("A phase-scoped check must reference a declared event.")
			check["event"] = event_key
		elif "event" in row:
			raise ValueError("Only event-scoped checks may reference an event.")
		checks.append(check)
	return {
		**normalize_structure(value, entities),
		"version": 1,
		"entities": list(entities.values()),
		"relations": relations,
		"events": sorted(events.values(), key=lambda r: (r["start"], r["id"])),
		**({"checks": checks} if checks else {}),
		**({"proportions": proportions} if proportions else {}),
	}


def instruction(plan, duration=None, start=None, end=None, *, include_events=True):
	contract = read_contract(plan, duration)
	if not contract:
		return ""
	labels = {r["id"]: r["label"] for r in contract["entities"]}
	parts = [
		f"{labels[r['subject']]} {RELATIONS[r['kind']]} {labels[r['object']]}" for r in contract["relations"]
	]
	actions = []
	for event in contract["events"]:
		if (start is not None and event["end"] <= start) or (end is not None and event["start"] >= end):
			continue
		# Earlier causes outside a continuation window are existing state, not instructions to replay.
		origin = start or 0
		first = max(event["start"], origin) - origin
		last = min(event["end"], end if end is not None else event["end"]) - origin
		if include_events:
			actions.append(f"{first:g}-{last:g}s: {event['description']}")
		for check in contract.get("checks", []):
			if check.get("event") == event["id"]:
				actions.append(f"{first:g}-{last:g}s only: {check['claim']}")
	parts.extend(proportion_claims(contract))
	parts.extend(structure_claims(contract))
	parts.extend(row["claim"] for row in contract.get("checks", []) if row["scope"] == "sequence")
	text = "; ".join(parts)
	if actions:
		text += (". Action timing: " if text else "Action timing: ") + "; ".join(actions)
	return "Physical staging: " + text + "." if text else ""


def review_questions(plan, duration=None):
	"""Bounded evidence requests; a judge cannot certify continuous physics from samples."""
	contract = read_contract(plan, duration)
	if not contract:
		return []
	labels = {r["id"]: r["label"] for r in contract["entities"]}
	questions = []
	for row in contract["relations"]:
		claim = f"{labels[row['subject']]} {RELATIONS[row['kind']]} {labels[row['object']]}"
		questions.append(
			(
				claim,
				"In these frames ordered left to right, top to bottom, is this relationship visibly supported wherever it can be seen: "
				+ claim
				+ "?",
			)
		)
	for row in contract["events"]:
		for cause in row["after"]:
			earlier = next(e for e in contract["events"] if e["id"] == cause)
			claim = earlier["description"] + " BEFORE " + row["description"]
			questions.append(
				(claim, "Do these time-ordered frames visibly establish this event order: " + claim + "?")
			)
	for claim in structure_claims(contract):
		questions.append(
			(
				claim,
				"Does the visible evidence support this authored structural requirement? Use uncertainty for hidden or ambiguous details: "
				+ claim,
			)
		)
	if len(questions) > 24:
		raise ValueError("Scene review exceeds the claim budget; simplify or split the scene.")
	return questions


def proportion_claims(contract):
	"""Authored physical scale, never a claim that perspective pixels were measured."""
	labels = {row["id"]: row["label"] for row in (contract or {}).get("entities", [])}
	return [
		f"The physical {row['axis']} of {labels[row['subject']]} is {row['min']:g}-{row['max']:g} "
		f"times the {row['axis']} of {labels[row['reference']]}; preserve this relative scale "
		"at comparable camera depth, accounting for perspective"
		for row in (contract or {}).get("proportions", [])
	]


def opening_claims(plan, duration=None):
	"""Static support/ownership and scale must reach the first image, before video."""
	contract = read_contract(plan, duration)
	if not contract:
		return []
	labels = {row["id"]: row["label"] for row in contract["entities"]}
	claims = [
		f"{labels[row['subject']]} {RELATIONS[row['kind']]} {labels[row['object']]}"
		for row in contract["relations"]
		if row["kind"] in {"attached_to", "supported_by"}
	]
	claims.extend(proportion_claims(contract))
	claims.extend(structure_claims(contract))
	claims.extend(row["claim"] for row in contract.get("checks", []) if row["scope"] == "opening")
	return claims


def opening_instruction(plan, duration=None):
	"""Only static authored requirements belong in the image stage; no future actions."""
	claims = opening_claims(plan, duration)
	return "Starting-frame staging: " + "; ".join(claims) + "." if claims else ""
