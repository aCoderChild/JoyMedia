"""Bind inferred physical entities to exact authored evidence, not image counts."""

import copy


def grounded_contract(authored, inferred, source):
	if not isinstance(inferred, dict):
		raise ValueError("Inferred scene constraints must be an object.")
	result = copy.deepcopy(authored)
	known = {row["id"] for row in result["entities"]}
	additional = inferred.get("additional_entities", [])
	if not isinstance(additional, list) or len(additional) > 8:
		raise ValueError("Declare at most eight authored props, supports, materials or body parts.")
	for row in additional:
		if not isinstance(row, dict) or set(row) != {"id", "source_quote", "kind"}:
			raise ValueError("Additional entities require id, source_quote and kind.")
		quote = row["source_quote"]
		if (
			row["kind"] not in {"prop", "support", "material", "body_part"}
			or not isinstance(quote, str)
			or not quote.strip()
			or len(quote) > 240
			or quote.casefold() not in source.casefold()
		):
			raise ValueError(
				"Additional entities must quote the authored scene; no additional actors or products."
			)
		if not isinstance(row["id"], str) or row["id"] in known:
			raise ValueError("Additional entities cannot replace a reference identity.")
		known.add(row["id"])
		result["entities"].append({"id": row["id"], "label": quote.strip()})
	for field in ("relations", "checks", "proportions", "counts", "parts", "properties", "transitions"):
		if field in inferred:
			result[field] = copy.deepcopy(inferred[field])
	return result
