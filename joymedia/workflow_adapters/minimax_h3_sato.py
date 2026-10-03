from .base import GenericWorkflowAdapter


class MiniMaxH3SatoAdapter(GenericWorkflowAdapter):
	"""Adapter for the exported MiniMax H3 Sato generation/continuation graphs."""

	cumulative_segment_output = True

	def extract_execution_metadata(self, workflow_data):
		generation = workflow_data.get("270", {}).get("inputs") or workflow_data.get("328", {}).get("inputs", {})
		return {
			"frame_count": int(generation.get("seconds", 5) * generation.get("fps", 24)),
			"output_fps": generation.get("fps", 24),
			"produces_video": 1,
			"produces_audio": 1,
		}

	def prepare_execution(
		self,
		workflow,
		*,
		seed,
		width,
		height,
		frame_count,
		output_prefix,
		last_frame_index,
		last_frame_prefix,
	):
		if "270" in workflow:
			_set_execution_input(workflow, "248", "seed", seed)
			_set_execution_input(workflow, "270", "width", width)
			_set_execution_input(workflow, "270", "height", height)
			_set_execution_input(workflow, "270", "seconds", max(1, round(frame_count / 24)))
			_set_execution_input(workflow, "270", "fps", 24)
			_set_execution_input(workflow, "254", "filename_prefix", output_prefix)
			_set_execution_input(workflow, "272", "filename_prefix", f"{output_prefix}_state")
			return workflow

		_set_execution_input(workflow, "291", "seed", seed)
		_set_execution_input(workflow, "328", "width", width)
		_set_execution_input(workflow, "328", "height", height)
		_set_execution_input(workflow, "328", "seconds", max(1, round(frame_count / 24)))
		_set_execution_input(workflow, "328", "segment_seconds", str(max(1, round(frame_count / 24))))
		_set_execution_input(workflow, "328", "fps", 24)
		_set_execution_input(workflow, "373", "filename_prefix", output_prefix)
		_set_execution_input(workflow, "374", "filename_prefix", f"{output_prefix}_stitched")
		_set_execution_input(workflow, "355", "filename_prefix", f"{output_prefix}_state")
		return workflow


def _set_execution_input(workflow, node_key, input_name, value):
	node = workflow.get(node_key)
	inputs = node.get("inputs") if isinstance(node, dict) else None
	if not isinstance(inputs, dict) or input_name not in inputs:
		raise ValueError(f"MiniMax H3 Sato workflow is missing execution input {node_key}.{input_name}")
	inputs[input_name] = value
