"""Script-derived preparation inventory, before any storyboard or visual job."""

import hashlib
import json
import re

ENVIRONMENT_KINDS = {"support", "furnishing", "background", "working_prop", "material"}


def script_fingerprint(script):
	return hashlib.sha256(json.dumps(script, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def environment_entities(scene):
	"""Every prepared object must have an exact authored source, never an invented cast member."""
	rows = scene.get("environment_entities") or []
	if not isinstance(rows, list) or len(rows) > 20:
		raise ValueError("Scene environment inventory must contain at most twenty objects.")
	text = " ".join(str(scene.get(k) or "") for k in ("place", "visual_camera", "action", "continuity_rules"))
	text = " ".join(text.split()).casefold()
	result = []
	for row in rows:
		if not isinstance(row, dict) or row.get("kind") not in ENVIRONMENT_KINDS:
			raise ValueError("Environment objects need a supported kind.")
		name = " ".join(str(row.get("name") or "").split())
		quote = " ".join(str(row.get("source_quote") or "").split())
		if re.search(
			r"\b(?:mascot|character|person|people|child|adult|bear|teddy)\b", name, re.I
		) or re.search(r"\b(?:product|retail pack|pack|package)\s*$", name, re.I):
			raise ValueError(
				f"Environment object {name!r} belongs in cast/products, not an empty location inventory."
			)
		if not name or not quote or quote.casefold() not in text or name.casefold() not in quote.casefold():
			raise ValueError(
				f"Environment object {name!r} is not grounded by source_quote {quote!r}. "
				"Copy a quote from THIS scene's place, visual_camera, action or continuity_rules "
				"that literally contains the object name. Remove the inventory entry if the object "
				"is not authored in this scene; a room name does not prove particular furniture. "
				f"Available scene text: {text}"
			)
		result.append({"name": name, "kind": row["kind"], "source_quote": quote})
	return result


def environment_staging(plan, scene_number):
	"""Only permanent setting objects belong in an empty shared location plate."""
	objects = []
	for room in (plan or {}).get("environments") or []:
		for row in room.get("objects") or []:
			if row.get("scene") == scene_number and row.get("kind") in {
				"support",
				"furnishing",
				"background",
			}:
				name = row.get("name")
				if name and name not in objects:
					objects.append(name)
	return ", ".join(objects)


def ground_generated_inventory(script):
	"""Remove invented AI inventory annotations without rewriting an authored story.

	The scene remains authoritative. Rejected inventory entries remain in the
	script's audit metadata; they never become instructions to add new objects.
	Explicit validation of supplied scripts still rejects ungrounded annotations.
	"""
	changes = []
	for index, scene in enumerate(script.get("scenes") or [], 1):
		rows = scene.get("environment_entities")
		if not isinstance(rows, list):
			continue
		grounded = []
		for row in rows:
			try:
				environment_entities({**scene, "environment_entities": [row]})
			except ValueError as exc:
				# A quote is a pointer into the authored scene, not a reason to add
				# missing furniture. Repair that pointer only when the literal name
				# already occurs in the scene and its role still passes validation.
				name = str(row.get("name") or "").strip() if isinstance(row, dict) else ""
				text = " ".join(
					str(scene.get(k) or "") for k in ("place", "visual_camera", "action", "continuity_rules")
				)
				match = re.search(re.escape(name), text, re.I) if name else None
				repaired = {**row, "source_quote": match.group()} if match else None
				if repaired:
					try:
						environment_entities({**scene, "environment_entities": [repaired]})
					except ValueError:
						pass
					else:
						grounded.append(repaired)
						script.setdefault("inventory_repairs", []).append(
							{"scene": index, "original": row, "repaired": repaired}
						)
						changes.append(f"Scene {index}: grounded {name!r} to its literal authored name.")
						continue
				script.setdefault("inventory_rejections", []).append(
					{"scene": index, "entry": row, "reason": str(exc)}
				)
				changes.append(f"Scene {index}: excluded unauthored environment inventory entry {row!r}.")
			else:
				grounded.append(row)
		scene["environment_entities"] = grounded
	return changes


def build_reference_plan(script, registry):
	groups = {}
	for group in registry:
		for key in [group["identity"], *(v["reference_key"] for v in group["views"])]:
			groups[(group["role"], key)] = group
	characters, products, environments, scenes = {}, {}, {}, []
	for index, scene in enumerate(script.get("scenes") or [], 1):
		cast, packs = [], []
		for field, roles, collection, names in (
			("cast", ("character", "person"), characters, cast),
			("products", ("product",), products, packs),
		):
			for key in scene.get(field) or []:
				group = next((groups[(role, key)] for role in roles if (role, key) in groups), None)
				if not group:
					raise ValueError(f"Scene {index} names an unregistered {field} identity: {key}")
				identity = group["identity"]
				names.append(identity)
				entry = collection.setdefault(
					identity,
					{
						"identity": identity,
						"label": group["label"],
						"original": group["original"],
						"requirements": [],
					},
				)
				entry["requirements"].append(
					{
						"scene": index,
						"reference_key": key,
						"opening": scene.get("visual_camera") or "",
						"action": scene.get("action") or "",
						"support": scene.get("opening_support") or "",
						**({"view": scene.get("product_view") or "source"} if field == "products" else {}),
					}
				)
		setting = " ".join(str(scene.get("place") or "").split())
		key = hashlib.sha256(setting.casefold().encode()).hexdigest()[:12]
		room = environments.setdefault(
			key, {"key": key, "setting": setting, "physical_cast": [], "objects": []}
		)
		for item in environment_entities(scene):
			room["objects"].append({**item, "scene": index})
		scenes.append({"scene": index, "cast_ids": cast, "product_ids": packs, "environment": key})
	return {
		"version": 1,
		"script_sha256": script_fingerprint(script),
		"engines": {
			"character": "H3 with qualified image fallback",
			"product": "H3 candidates; supplied artwork remains authoritative",
			"environment": "Configured image workflow (Flux)",
		},
		"characters": list(characters.values()),
		"products": list(products.values()),
		"environments": list(environments.values()),
		"scenes": scenes,
		"pose_requirements": [],
		"prepared_poses": [],
		"prepared_products": [],
		"action_transport": "Authored timed actions and qualified opening frames; no unsupported motion-reference channel is implied.",
	}
