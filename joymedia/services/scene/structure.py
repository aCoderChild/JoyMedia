"""Bounded structural requirements. Counts and geometry are supplied by a case, never inferred from its name."""

VISIBILITY = {"visible", "occlusion_allowed"}


def normalize_structure(value, entities):
	def rows(key, limit=8):
		result = value.get(key, [])
		if (
			not isinstance(result, list)
			or len(result) > limit
			or any(not isinstance(row, dict) for row in result)
		):
			raise ValueError(f"Scene contract {key} must contain at most {limit} objects.")
		return result

	def entity(row):
		identifier = row.get("entity")
		if not isinstance(identifier, str) or identifier not in entities:
			raise ValueError("Structural requirements must name a declared entity.")
		return identifier

	def text(value):
		if not isinstance(value, str) or not value.strip() or len(value) > 240:
			raise ValueError("Structural labels and properties must contain 1 to 240 characters.")
		return " ".join(value.split())

	def count(row, allow_zero=False):
		number = row.get("count")
		if type(number) is not int or not (0 if allow_zero else 1) <= number <= 64:
			raise ValueError(
				"Structural counts must be integers up to 64; only absent parts may have count zero."
			)
		return number

	def visibility(row):
		mode = row.get("visibility", "occlusion_allowed")
		if not isinstance(mode, str) or mode not in VISIBILITY:
			raise ValueError("Structural visibility must be visible or occlusion_allowed.")
		return mode

	result, seen = {}, set()
	for key in ("counts", "parts", "properties"):
		normalized = []
		for row in rows(key):
			allowed = (
				{"entity", "name", "value"}
				if key == "properties"
				else {"entity", "count", "visibility"} | ({"label"} if key == "parts" else set())
			)
			if set(row) - allowed:
				raise ValueError("Unsupported structural requirement fields.")
			item = {"entity": entity(row)}
			if key == "properties":
				item.update(name=text(row.get("name")), value=text(row.get("value")))
			else:
				if key == "parts":
					item["label"] = text(row.get("label"))
				item.update(count=count(row, allow_zero=key == "parts"), visibility=visibility(row))
			identity = (key, item["entity"], (item.get("label") or item.get("name") or "").casefold())
			if identity in seen:
				raise ValueError("Declare each entity count, structural part and property once.")
			seen.add(identity)
			normalized.append(item)
		if normalized:
			result[key] = normalized
	return result


def structure_claims(contract):
	labels = {row["id"]: row["label"] for row in (contract or {}).get("entities", [])}
	claims = []
	for row in (contract or {}).get("counts", []):
		visibility = (
			"All instances must be visible."
			if row["visibility"] == "visible"
			else "Occlusion may hide instances; do not invent additional instances."
		)
		claims.append(
			f"Exactly {row['count']} physical instance(s) of {labels[row['entity']]} exist in the scene. {visibility}"
		)
	for row in (contract or {}).get("parts", []):
		if row["count"] == 0:
			claims.append(
				f"{labels[row['entity']]} has no {row['label']}; do not invent these parts, including during motion."
			)
			continue
		visibility = (
			"All declared parts must be visible."
			if row["visibility"] == "visible"
			else "Some parts may be hidden by plausible occlusion; not every part must be visible."
		)
		claims.append(
			f"{labels[row['entity']]} has exactly {row['count']} {row['label']}; visible parts remain connected to that object with consistent geometry. {visibility}"
		)
	for row in (contract or {}).get("properties", []):
		claims.append(f"Preserve {labels[row['entity']]}'s {row['name']}: {row['value']}.")
	return claims
