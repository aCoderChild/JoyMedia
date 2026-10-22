"""Data-driven adapter for ordinary ComfyUI API workflows.

New model families can use this adapter by declaring their node mappings and
supported values in Generation Workflow.Execution Specification.
"""

from __future__ import annotations

import re

from .base import GenericWorkflowAdapter

SUPPORTED_PARAMETERS = {
	"seed",
	"width",
	"height",
	"aspect_ratio",
	"frame_count",
	"fps",
	"output_prefix",
	"last_frame_prefix",
	"last_frame_index",
}
SUPPORTED_TRANSFORMS = {
	"identity",
	"frames_to_seconds",
	"aspect_ratio_option",
	"nearest_size_dimension",
	"round_to_multiple",
	"ceil_to_multiple",
}
METADATA_FIELDS = {
	"frame_count",
	"output_fps",
	"output_media_type",
	"primary_output_node_key",
	"primary_artifact_role",
	"produces_video",
	"produces_audio",
}


class GenericComfyUIAdapter(GenericWorkflowAdapter):
	"""Populate declaratively mapped ComfyUI node inputs with JoyMedia values."""

	def validate_specification(self, workflow_data):
		spec = self.execution_spec
		if not isinstance(spec, dict):
			raise ValueError("Execution Specification must be a JSON object")
		from joymedia.services.workflows.capabilities import validate_contract

		validate_contract(spec)
		parameters = spec.get("parameters") or []
		if not isinstance(parameters, list):
			raise ValueError("Execution Specification 'parameters' must be a list")
		for mapping in parameters:
			if not isinstance(mapping, dict):
				raise ValueError("Each execution parameter mapping must be an object")
			semantic = mapping.get("semantic")
			if semantic not in SUPPORTED_PARAMETERS:
				raise ValueError(f"Unsupported execution parameter semantic: {semantic}")
			transform = mapping.get("transform", "identity")
			if transform not in SUPPORTED_TRANSFORMS:
				raise ValueError(f"Unsupported execution parameter transform: {transform}")
			self._validate_node_input(workflow_data, mapping)
			if transform == "aspect_ratio_option" and not mapping.get("options"):
				raise ValueError("aspect_ratio_option mappings require an options object")
			if transform == "aspect_ratio_option":
				options = mapping["options"]
				if not isinstance(options, dict) or not options:
					raise ValueError("aspect_ratio_option options must be a non-empty object")
				try:
					if any(float(ratio) <= 0 for ratio in options.values()):
						raise ValueError("aspect_ratio_option ratios must be greater than zero")
				except (TypeError, ValueError) as exc:
					raise ValueError("aspect_ratio_option ratios must be positive numbers") from exc
			if transform == "nearest_size_dimension":
				options = mapping.get("options")
				if mapping.get("dimension") not in {"width", "height"}:
					raise ValueError("nearest_size_dimension requires dimension 'width' or 'height'")
				if not isinstance(options, list) or not options:
					raise ValueError("nearest_size_dimension requires a non-empty size options list")
				if any(
					not isinstance(size, dict)
					or float(size.get("width", 0)) <= 0
					or float(size.get("height", 0)) <= 0
					for size in options
				):
					raise ValueError("nearest_size_dimension options need positive width and height values")
				if mapping.get("fallback_multiple") is not None and int(mapping["fallback_multiple"]) < 1:
					raise ValueError("nearest_size_dimension fallback_multiple must be a positive integer")
			if transform in {"round_to_multiple", "ceil_to_multiple"}:
				try:
					if int(mapping["multiple"]) < 1:
						raise ValueError
				except (KeyError, TypeError, ValueError) as exc:
					raise ValueError("round_to_multiple requires a positive integer 'multiple'") from exc
			if transform == "ceil_to_multiple":
				offset = mapping.get("offset", 0)
				if type(offset) is not int or not 0 <= offset < int(mapping["multiple"]):
					raise ValueError("ceil_to_multiple offset must be an integer within the multiple")

			if transform == "frames_to_seconds" and mapping.get("fps") is not None:
				try:
					if float(mapping["fps"]) <= 0:
						raise ValueError("frames_to_seconds fps must be greater than zero")
				except (TypeError, ValueError) as exc:
					raise ValueError("frames_to_seconds fps must be a positive number") from exc

		outputs = spec.get("outputs") or {}
		if not isinstance(outputs, dict):
			raise ValueError("Execution Specification 'outputs' must be an object")
		primary = outputs.get("primary")
		if not isinstance(primary, dict):
			raise ValueError("Execution Specification must declare outputs.primary")
		for output_name in ("primary", "last_frame"):
			output = outputs.get(output_name)
			if output:
				if not isinstance(output, dict):
					raise ValueError(f"Output '{output_name}' must be an object")
				node_key = str(output.get("node_key") or "")
				if node_key not in workflow_data:
					raise ValueError(f"Output '{output_name}' references missing node {node_key}")
				if output_name == "primary" and not output.get("media_type"):
					raise ValueError("The primary output declaration requires media_type")
				if output_name == "primary" and output.get("media_type") not in {"Image", "Video", "Audio"}:
					raise ValueError("Primary output media_type must be Image, Video, or Audio")
				if output_name == "last_frame" and output.get("media_type", "Image") != "Image":
					raise ValueError("The last_frame output must be an Image")

		metadata = spec.get("metadata") or {}
		if not isinstance(metadata, dict):
			raise ValueError("Execution Specification 'metadata' must be an object")
		unknown = set(metadata) - METADATA_FIELDS
		if unknown:
			raise ValueError(f"Unsupported execution metadata fields: {', '.join(sorted(unknown))}")
		preprocessing = spec.get("input_preprocessing") or {}
		if not isinstance(preprocessing, dict):
			raise ValueError("Execution Specification 'input_preprocessing' must be an object")
		for key in ("compose_image_roles", "scalarize_single_path_roles"):
			if not isinstance(preprocessing.get(key, []), list):
				raise ValueError(f"input_preprocessing.{key} must be a list")
		for branch in preprocessing.get("optional_reference_branches") or []:
			if not isinstance(branch, dict) or not branch.get("role"):
				raise ValueError("Each optional_reference_branches entry requires a role")
			for key in ("image_node", "scale_node", "encode_node", "positive_node", "negative_node"):
				node_key = str(branch.get(key) or "")
				if node_key not in workflow_data:
					raise ValueError(f"Optional reference branch references missing node {node_key}")
			for key in ("image_node", "scale_node", "encode_node", "positive_node", "negative_node"):
				if key not in branch:
					raise ValueError(f"Optional reference branch requires {key}")
				if not isinstance(branch.get("branch_nodes"), list) or not branch["branch_nodes"]:
					raise ValueError("Optional reference branch requires a non-empty branch_nodes list")
				if any(node_key not in workflow_data for node_key in branch["branch_nodes"]):
					raise ValueError("Optional reference branch contains an unknown node")
		base_conditioning = preprocessing.get("reference_conditioning_base") or {}
		if base_conditioning:
			for key in ("positive_node", "negative_node"):
				if base_conditioning.get(key) not in workflow_data:
					raise ValueError(f"input_preprocessing.reference_conditioning_base requires valid {key}")
				target_key = key.replace("_node", "_target")
				if not base_conditioning.get(target_key):
					raise ValueError(f"input_preprocessing.reference_conditioning_base requires {target_key}")
				target = base_conditioning[target_key]
				self._validate_node_input(
					workflow_data,
					{
						"semantic": "reference conditioning output",
						"node_key": target.get("node_key"),
						"input_name": target.get("input_name"),
					},
				)
		for chain in preprocessing.get("optional_input_chains") or []:
			self._validate_input_chain(workflow_data, chain)
		mirrors = spec.get("input_mirrors", [])
		if not isinstance(mirrors, list) or len(mirrors) > 16:
			raise ValueError("input_mirrors must contain at most 16 independent input copies")
		sources, targets = set(), set()
		for mirror in mirrors:
			if not isinstance(mirror, dict):
				raise ValueError("Each input mirror requires source and target inputs")
			for side in ("source", "target"):
				value = mirror.get(side)
				if not isinstance(value, dict):
					raise ValueError("Each input mirror requires source and target inputs")
				self._validate_node_input(workflow_data, {"semantic": "input mirror", **value})
			source, target = (
				tuple(str(mirror[side][key]) for key in ("node_key", "input_name"))
				for side in ("source", "target")
			)
			if target in targets:
				raise ValueError("Input mirror targets must be unique")
			sources.add(source)
			targets.add(target)
		if sources & targets:
			raise ValueError("Input mirrors must be independent; chains and cycles are not supported")

		for operation in spec.get("conditional_inputs") or []:
			if not isinstance(operation, dict) or not operation.get("role"):
				raise ValueError("Each conditional_inputs entry requires a role")
			target = operation.get("target") or {}
			self._validate_node_input(
				workflow_data,
				{
					"semantic": "conditional input",
					"node_key": target.get("node_key"),
					"input_name": target.get("input_name"),
				},
			)
			if "when_present" not in operation or "when_absent" not in operation:
				raise ValueError("Conditional input operations require when_present and when_absent values")
		for operation in spec.get("prompt_transforms") or []:
			if not isinstance(operation, dict):
				raise ValueError("Each prompt_transforms entry must be an object")
			self._validate_node_input(workflow_data, operation)
			if not isinstance(operation.get("remove_patterns", []), list):
				raise ValueError("prompt_transforms.remove_patterns must be a list")
			if "when_role_present" in operation and (
				not isinstance(operation["when_role_present"], str)
				or not operation["when_role_present"].strip()
			):
				raise ValueError("prompt_transforms.when_role_present must name a nonempty input role")

	def _validate_input_chain(self, workflow_data, chain):
		if not isinstance(chain, dict) or not isinstance(chain.get("links"), list) or not chain["links"]:
			raise ValueError("Each optional_input_chains entry requires a non-empty links list")
		self._validate_node_input(
			workflow_data, {"semantic": "input chain target", **(chain.get("target") or {})}
		)
		base = chain.get("base")
		if not isinstance(base, list) or len(base) != 2 or str(base[0]) not in workflow_data:
			raise ValueError("Input chain base must be [node_key, output_index] of an existing node")
		for link in chain["links"]:
			if not isinstance(link, dict) or not link.get("role"):
				raise ValueError("Each input chain link requires a role")
			nodes = link.get("nodes")
			if not isinstance(nodes, list) or any(str(node) not in workflow_data for node in nodes or []):
				raise ValueError("Input chain link nodes must list existing nodes")
			self._validate_node_input(
				workflow_data,
				{
					"semantic": "input chain link",
					"node_key": link.get("node"),
					"input_name": link.get("input"),
				},
			)

	@staticmethod
	def _finalize_optional_input_chains(workflow, preprocessing, staged_inputs):
		"""Splice each present link into a single-stream chain; drop the nodes of absent links.

		The chain starts at ``base`` and every present link consumes the previous
		source through ``link.input`` and exposes ``link.node``'s output; the final
		source is wired into ``target``. Any graph input (conditioning, model, ...) can
		be chained this way, so absent references never leave dangling nodes.
		"""
		for chain in preprocessing.get("optional_input_chains") or []:
			source = [str(chain["base"][0]), int(chain["base"][1])]
			for link in chain["links"]:
				if not _link_present(staged_inputs, link):
					for node_key in link["nodes"]:
						workflow.pop(str(node_key), None)
					continue
				workflow[str(link["node"])]["inputs"][str(link["input"])] = source
				source = [str(link["node"]), int(link.get("output", 0))]
			target = chain["target"]
			workflow[str(target["node_key"])]["inputs"][str(target["input_name"])] = source

	def extract_execution_metadata(self, workflow_data):
		self.validate_specification(workflow_data)
		metadata = dict(self.execution_spec.get("metadata") or {})
		primary = (self.execution_spec.get("outputs") or {}).get("primary") or {}
		if primary:
			metadata["primary_output_node_key"] = str(primary["node_key"])
			metadata["output_media_type"] = primary["media_type"]
			metadata.setdefault(
				"primary_artifact_role",
				{"Image": "Primary Image", "Video": "Primary Video", "Audio": "Primary Audio"}.get(
					primary["media_type"], "Intermediate"
				),
			)
		return metadata

	def prepare_execution(
		self,
		workflow,
		*,
		seed,
		width,
		height,
		fps=None,
		frame_count=None,
		output_prefix,
		last_frame_index=None,
		last_frame_prefix=None,
	):
		values = {
			"seed": seed,
			"width": width,
			"height": height,
			"aspect_ratio": float(width) / float(height) if height else None,
			"frame_count": frame_count,
			"fps": fps,
			"output_prefix": output_prefix,
			"last_frame_prefix": last_frame_prefix,
			"last_frame_index": last_frame_index,
		}
		for mapping in self.execution_spec.get("parameters") or []:
			semantic = mapping["semantic"]
			value = values[semantic]
			if value is None:
				continue
			value = _transform_value(mapping, value, values)
			self._set_node_input(workflow, mapping, value)
		return workflow

	def finalize_workflow(self, workflow, workflow_version, staged_inputs):
		preprocessing = self.execution_spec.get("input_preprocessing") or {}
		self._finalize_optional_reference_branches(workflow, preprocessing, staged_inputs)
		self._finalize_optional_input_chains(workflow, preprocessing, staged_inputs)
		composed_roles = {str(role) for role in preprocessing.get("compose_image_roles") or []}
		# File Paths are staged as lists throughout the runner, but a ComfyUI
		# LoadImage.image input is a scalar filename. Respect the workflow's
		# declared cardinality instead of requiring model-specific preprocessing.
		for binding in getattr(workflow_version, "bindings", ()) or ():
			role = getattr(binding, "required_input_role", None)
			if not role or getattr(binding, "value_type", None) != "File Paths":
				continue
			is_multiple = str(getattr(binding, "allow_multiple", False)).strip().lower() in {
				"1",
				"true",
				"yes",
			}
			# A composed board starts as many references but is staged as exactly
			# one PNG for a normal ComfyUI LoadImage node.
			if is_multiple and str(role) not in composed_roles:
				continue
			values = staged_inputs.get(role) or []
			if not isinstance(values, (list, tuple)):
				values = [values]
			if len(values) == 1:
				workflow[str(binding.node_key)]["inputs"][binding.input_name] = values[0]

		for mirror in self.execution_spec.get("input_mirrors", []):
			import copy

			source, target = mirror["source"], mirror["target"]
			value = workflow[str(source["node_key"])]["inputs"][source["input_name"]]
			self._set_node_input(workflow, {"semantic": "input mirror", **target}, copy.deepcopy(value))

		for operation in self.execution_spec.get("conditional_inputs") or []:
			role = str(operation["role"])
			value = operation["when_present"] if staged_inputs.get(role) else operation["when_absent"]
			target = operation["target"]
			self._set_node_input(
				workflow,
				{
					"semantic": "conditional input",
					"node_key": target["node_key"],
					"input_name": target["input_name"],
				},
				value,
			)

		for operation in self.execution_spec.get("prompt_transforms") or []:
			if operation.get("when_role_present") and not staged_inputs.get(operation["when_role_present"]):
				continue
			node_key, input_name = str(operation["node_key"]), operation["input_name"]
			text = str(workflow[node_key]["inputs"].get(input_name) or "")
			for pattern in operation.get("remove_patterns") or []:
				text = re.sub(pattern, "", text, flags=re.IGNORECASE)
			text = re.sub(r"(?:\s*,\s*){2,}", ", ", text).strip(" ,.;\n\t")
			append = str(operation.get("append_text") or "").strip()
			staged_key = operation.get("append_staged_text_key")
			if staged_key:
				append = ". ".join(
					part for part in (append, str(staged_inputs.get(staged_key) or "").strip()) if part
				)
			if append and append.lower() not in text.lower():
				text = f"{text}. {append}".strip(". ") if text else append
			workflow[node_key]["inputs"][input_name] = text.rstrip(". ") + "."
		return workflow

	@staticmethod
	def _finalize_optional_reference_branches(workflow, preprocessing, staged_inputs):
		branches = preprocessing.get("optional_reference_branches") or []
		if not branches:
			return
		base = preprocessing["reference_conditioning_base"]
		positive_source = [base["positive_node"], int(base.get("positive_output", 0))]
		negative_source = [base["negative_node"], int(base.get("negative_output", 0))]
		for branch in branches:
			present = bool(staged_inputs.get(branch["role"]))
			if not present:
				for node_key in branch["branch_nodes"]:
					workflow.pop(str(node_key), None)
				continue
			positive_key = str(branch["positive_node"])
			negative_key = str(branch["negative_node"])
			workflow[positive_key]["inputs"][str(branch.get("conditioning_input", "conditioning"))] = (
				positive_source
			)
			workflow[negative_key]["inputs"][str(branch.get("conditioning_input", "conditioning"))] = (
				negative_source
			)
			positive_source = [positive_key, int(branch.get("positive_output", 0))]
			negative_source = [negative_key, int(branch.get("negative_output", 0))]
		for stream, source in (("positive", positive_source), ("negative", negative_source)):
			target = base[f"{stream}_target"]
			workflow[str(target["node_key"])]["inputs"][str(target["input_name"])] = source

	def _set_node_input(self, workflow, mapping, value):
		self._validate_node_input(workflow, mapping)
		workflow[str(mapping["node_key"])]["inputs"][mapping["input_name"]] = value

	@staticmethod
	def _validate_node_input(workflow, mapping):
		node_key = str(mapping.get("node_key") or "")
		input_name = mapping.get("input_name")
		node = workflow.get(node_key)
		if not isinstance(node, dict) or input_name not in (node.get("inputs") or {}):
			raise ValueError(
				f"Execution mapping for {mapping.get('semantic')} points to missing input {node_key}.{input_name}"
			)


def _transform_value(mapping, value, values):
	transform = mapping.get("transform", "identity")
	if transform == "identity":
		return value
	if transform == "ceil_to_multiple":
		import math

		multiple, offset = int(mapping["multiple"]), mapping.get("offset", 0)
		return max(offset or multiple, math.ceil((float(value) - offset) / multiple) * multiple + offset)

	if transform == "round_to_multiple":
		# A model whose latent grid needs sizes divisible by N (for example 32) rejects anything else, so a
		# delivery size such as 720 (22.5 x 32) is rounded to the nearest valid size (half rounds up).
		multiple = int(mapping["multiple"])
		return max(multiple, int(float(value) / multiple + 0.5) * multiple)
	if transform == "frames_to_seconds":
		fps = float(mapping.get("fps") or values.get("fps") or 24)
		if fps <= 0:
			raise ValueError("frames_to_seconds fps must be greater than zero")
		seconds = float(values.get("frame_count") or 0) / fps
		minimum = float(mapping.get("minimum", 0))
		return max(minimum, seconds)
	if transform == "aspect_ratio_option":
		ratio = float(values["width"]) / float(values["height"])
		options = mapping["options"]
		if not isinstance(options, dict) or not options:
			raise ValueError("aspect_ratio_option options must be a non-empty object")
		return min(options, key=lambda label: abs(float(options[label]) - ratio))
	if transform == "nearest_size_dimension":
		ratio = float(values["width"]) / float(values["height"])
		option = min(
			mapping["options"],
			key=lambda size: abs(float(size["width"]) / float(size["height"]) - ratio),
		)
		# A model's native sizes cover only some ratios; any other delivery ratio keeps
		# its own shape, aligned to the latent grid (docs/input-authority.md).
		error = abs(float(option["width"]) / float(option["height"]) - ratio) / ratio
		if mapping.get("fallback_multiple") and error > float(mapping.get("max_ratio_error", 0)):
			multiple = int(mapping["fallback_multiple"])
			return max(multiple, int(float(values[mapping["dimension"]]) / multiple + 0.5) * multiple)
		return int(option[mapping["dimension"]])
	return value  # validate_specification rejects transforms outside the allowlist


def _link_present(staged_inputs, link):
	"""Whether a chain link has its input: a link with a `slot` takes the slot-th picture of its role (0-based)."""
	value = staged_inputs.get(link["role"])
	slot = int(link.get("slot", 0))
	if isinstance(value, (list, tuple)):
		return len(value) > slot
	return bool(value) and slot == 0
