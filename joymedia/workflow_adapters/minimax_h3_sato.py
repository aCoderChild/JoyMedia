from .base import GenericWorkflowAdapter


class MiniMaxH3SatoGenerationAdapter(GenericWorkflowAdapter):
	"""Adapter for the exported MiniMax H3 Sato initial-generation graph."""

	continuation_workflow_key = "h3_sato_continuation"
	cumulative_segment_output = True
	primary_output_node_keys = ("254", "374")
	continuation_overlap_frames = 22

	def extract_execution_metadata(self, workflow_data):
		return _extract_metadata(workflow_data, "270")

	def prepare_execution(
		self,
		workflow,
		*,
		seed,
		width,
		height,
		fps=None,
		frame_count,
		output_prefix,
		last_frame_index,
		last_frame_prefix,
	):
		fps = float(fps or 24)
		_set_execution_input(workflow, "248", "seed", seed)
		_set_execution_input(workflow, "270", "width", width)
		_set_execution_input(workflow, "270", "height", height)
		_set_execution_input(workflow, "270", "seconds", frame_count / fps)
		_set_execution_input(workflow, "270", "fps", fps)
		_set_execution_input(workflow, "254", "filename_prefix", output_prefix)
		_set_execution_input(workflow, "272", "filename_prefix", f"{output_prefix}_state")
		return workflow


class MiniMaxH3SatoContinuationAdapter(GenericWorkflowAdapter):
	"""Adapter for the exported MiniMax H3 Sato cumulative continuation graph."""

	cumulative_segment_output = True
	primary_output_node_keys = ("374", "254")
	continuation_overlap_frames = 22

	def extract_execution_metadata(self, workflow_data):
		return _extract_metadata(workflow_data, "328")

	def prepare_execution(
		self,
		workflow,
		*,
		seed,
		width,
		height,
		fps=None,
		frame_count,
		output_prefix,
		last_frame_index,
		last_frame_prefix,
	):
		fps = float(fps or 24)
		duration = frame_count / fps
		_set_execution_input(workflow, "291", "seed", seed)
		_set_execution_input(workflow, "328", "width", width)
		_set_execution_input(workflow, "328", "height", height)
		_set_execution_input(workflow, "328", "seconds", duration)
		_set_execution_input(workflow, "328", "segment_seconds", str(duration))
		_set_execution_input(workflow, "328", "fps", fps)
		_set_execution_input(workflow, "355", "filename_prefix", f"{output_prefix}_state")
		_set_execution_input(workflow, "374", "filename_prefix", output_prefix)
		return workflow


class MiniMaxH3SatoAdapter(GenericWorkflowAdapter):
	"""Compatibility adapter for workflow records created before split adapter keys."""

	continuation_workflow_key = "h3_sato_continuation"
	cumulative_segment_output = True

	def extract_execution_metadata(self, workflow_data):
		adapter = (
			MiniMaxH3SatoGenerationAdapter()
			if "270" in workflow_data
			else MiniMaxH3SatoContinuationAdapter()
		)
		return adapter.extract_execution_metadata(workflow_data)

	def prepare_execution(self, workflow, **kwargs):
		adapter = MiniMaxH3SatoGenerationAdapter() if "270" in workflow else MiniMaxH3SatoContinuationAdapter()
		return adapter.prepare_execution(workflow, **kwargs)


def _extract_metadata(workflow_data, node_key):
	inputs = workflow_data.get(node_key, {}).get("inputs", {})
	fps = float(inputs.get("fps", 24))
	return {
		"frame_count": int(float(inputs.get("seconds", 5)) * fps),
		"output_fps": fps,
		"produces_video": 1,
		"produces_audio": 1,
	}


def _set_execution_input(workflow, node_key, input_name, value):
	node = workflow.get(node_key)
	inputs = node.get("inputs") if isinstance(node, dict) else None
	if not isinstance(inputs, dict) or input_name not in inputs:
		raise ValueError(f"MiniMax H3 Sato workflow is missing execution input {node_key}.{input_name}")
	inputs[input_name] = value
