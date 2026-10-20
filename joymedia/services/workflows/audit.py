"""Audit API and UI exports against an installed ComfyUI server without queueing.

python -m joymedia.services.workflows.audit --object-info snapshot.json workflow.json ...
An API companion can be written with --output-dir. UI conversion uses the target
server's widget order, and rejects ambiguous or obsolete widget lists.
"""

import argparse
import json
from pathlib import Path

from joymedia.services.workflows.schema import graph_schema_errors


def api_graph(export, object_info):
	if "prompt" in export:
		return export["prompt"]
	if "nodes" not in export:
		return export
	links = {link[0]: link for link in export.get("links", [])}
	graph = {}
	for node in export["nodes"]:
		key, kind = str(node["id"]), node["type"]
		if node.get("mode", 0) != 0:
			raise ValueError(f"{key}: bypassed/muted nodes require a ComfyUI API export")
		if kind not in object_info:
			raise ValueError(f"{key}: {kind} is not installed")
		schema = object_info[kind]
		inputs = {}
		for slot, port in enumerate(node.get("inputs", [])):
			if port.get("link") is not None:
				link = links[port["link"]]
				if str(link[3]) != key or link[4] != slot:
					raise ValueError(f"{key}.{port['name']}: UI link destination mismatch")
				inputs[port["name"]] = [str(link[1]), link[2]]
		widgets = node.get("widgets_values") or []
		if isinstance(widgets, dict):
			inputs.update(widgets)
		else:
			cursor = 0
			for group in ("required", "optional"):
				contracts = (schema.get("input") or {}).get(group) or {}
				order = (schema.get("input_order") or {}).get(group) or list(contracts)
				for name in order:
					contract = contracts[name]
					kind_name = contract[0]
					options = contract[1] if len(contract) > 1 and isinstance(contract[1], dict) else {}
					if name in inputs or options.get("forceInput"):
						continue
					if not isinstance(kind_name, list) and kind_name not in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"):
						continue
					if cursor >= len(widgets):
						if group == "required":
							raise ValueError(f"{key}.{name}: UI widget value is missing")
						continue
					inputs[name] = widgets[cursor]
					cursor += 1
					if options.get("control_after_generate") or name in ("seed", "noise_seed"):
						if cursor < len(widgets) and widgets[cursor] in ("fixed", "increment", "decrement", "randomize"):
							cursor += 1
			if cursor < len(widgets):
				# LoadImage's upload button has a UI-only widget; it is not an API input.
				if not (kind == "LoadImage" and widgets[cursor:] == ["image"]):
					raise ValueError(f"{key}: {len(widgets) - cursor} unrecognized UI widget values; export API format from this server")
		graph[key] = {"class_type": kind, "inputs": inputs}
	return graph


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--object-info", type=Path, required=True)
	parser.add_argument("--output-dir", type=Path)
	parser.add_argument("files", nargs="+", type=Path)
	args = parser.parse_args()
	info = json.loads(args.object_info.read_text())
	failed = False
	for path in args.files:
		try:
			graph = api_graph(json.loads(path.read_text()), info)
			errors = graph_schema_errors(graph, info)
			if errors:
				raise ValueError("; ".join(errors))
			print(f"PASS {path}: {len(graph)} nodes")
			if args.output_dir:
				args.output_dir.mkdir(parents=True, exist_ok=True)
				(args.output_dir / f"{path.stem}_api.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n")
		except (ValueError, KeyError, TypeError) as exc:
			failed = True
			print(f"FAIL {path}: {exc}")
	return int(failed)


if __name__ == "__main__":
	raise SystemExit(main())
