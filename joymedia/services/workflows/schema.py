"""Read-only checks against the target ComfyUI /object_info contract.

This deliberately does not submit prompts, load models, or guess UI widget order.
Dynamic inputs and custom validation remain the server's responsibility.
"""

from __future__ import annotations


def graph_schema_errors(graph, object_info, *, bound_inputs=()):
	"""Return actionable schema errors; bound placeholders are checked after staging."""
	errors = []
	bound = {(str(node), name) for node, name in bound_inputs}
	for key, node in graph.items():
		kind = node.get("class_type")
		schema = object_info.get(kind)
		if schema is None:
			errors.append(f"{key}: node type {kind} is not installed")
			continue
		groups = schema.get("input") or {}
		required = groups.get("required") or {}
		declared = {**required, **(groups.get("optional") or {})}
		inputs = node.get("inputs") or {}
		for name in required.keys() - inputs.keys():
			if not any(input_name.startswith(name + ".") for input_name in inputs):
				errors.append(f"{key}.{name}: required input is missing")
		for name, value in inputs.items():
			contract = declared.get(name)
			# V3 autogrow/dynamic inputs have flattened names; the server validates them.
			if contract is None:
				continue
			type_name = contract[0]
			options = contract[1] if len(contract) > 1 and isinstance(contract[1], dict) else {}
			if (
				isinstance(value, list)
				and len(value) == 2
				and isinstance(value[0], str)
				and type(value[1]) is int
			):
				source = graph.get(value[0])
				if source is None:
					errors.append(f"{key}.{name}: source node {value[0]} is missing")
					continue
				outputs = (object_info.get(source.get("class_type")) or {}).get("output")
				if outputs is not None:
					if value[1] < 0 or value[1] >= len(outputs):
						errors.append(f"{key}.{name}: source output {value[0]}[{value[1]}] does not exist")
					elif isinstance(type_name, str) and type_name not in {
						"*",
						"COMFY_DYNAMICCOMBO_V3",
						"COMFY_MATCHTYPE_V3",
					}:
						actual = outputs[value[1]]
						if (
							isinstance(actual, str)
							and actual not in {"*", "COMFY_MATCHTYPE_V3"}
							and not set(actual.split(",")) & set(type_name.split(","))
						):
							errors.append(f"{key}.{name}: expected {type_name}, got {actual} from {value[0]}")
				continue
			if (str(key), name) in bound or (value is None and name not in required):
				continue
			choices = (
				type_name
				if isinstance(type_name, list)
				else options.get("options")
				if type_name == "COMBO"
				else None
			)
			if choices is not None and value not in choices:
				errors.append(f"{key}.{name}: {value!r} is not an installed/allowed option")
			if type_name in ("INT", "FLOAT"):
				if (
					isinstance(value, bool)
					or not isinstance(value, (int, float))
					or (type_name == "INT" and not isinstance(value, int))
				):
					errors.append(f"{key}.{name}: expected {type_name}")
				elif value < options.get("min", float("-inf")) or value > options.get("max", float("inf")):
					errors.append(f"{key}.{name}: {value} is outside the supported range")
	# A graph can have individually valid sockets and still contain a dependency
	# cycle. Check all links, including flattened V3 inputs, without recursion.
	dependencies = {str(key): set() for key in graph}
	for key, node in graph.items():
		for value in (node.get("inputs") or {}).values():
			if (
				isinstance(value, list)
				and len(value) == 2
				and isinstance(value[0], str)
				and type(value[1]) is int
				and value[0] in dependencies
			):
				dependencies[str(key)].add(value[0])
	ready = [key for key, parents in dependencies.items() if not parents]
	visited = set()
	while ready:
		key = ready.pop()
		if key in visited:
			continue
		visited.add(key)
		for target, parents in dependencies.items():
			if key in parents:
				parents.remove(key)
				if not parents:
					ready.append(target)
	if len(visited) < len(dependencies):
		errors.append("Dependency cycle involving: " + ", ".join(sorted(set(dependencies) - visited)))
	return errors
