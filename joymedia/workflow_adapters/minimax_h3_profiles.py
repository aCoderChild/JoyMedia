from .base import GenericWorkflowAdapter


H3_PROFILE_DEFAULTS = {
	"output_fps": 24,
	"frame_count": 124,
	"produces_video": 1,
	"produces_audio": 1,
}


class MiniMaxH3ImageToVideoAdapter(GenericWorkflowAdapter):
	"""Adapter for the exported MiniMax H3 Image-to-Video API graph."""

	def extract_execution_metadata(self, workflow_data):
		return dict(H3_PROFILE_DEFAULTS)

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
		_set_input(workflow, "105:15", "noise_seed", seed)
		_set_input(workflow, "105:111", "value", max(5, frame_count / 24))
		_set_input(workflow, "105:104", "width", width)
		_set_input(workflow, "105:104", "height", height)
		_set_input(workflow, "92", "filename_prefix", output_prefix)
		return workflow


class MiniMaxH3ReferenceToVideoAdapter(GenericWorkflowAdapter):
	"""Adapter for the exported MiniMax H3 Reference-to-Video API graphs."""

	def extract_execution_metadata(self, workflow_data):
		return dict(H3_PROFILE_DEFAULTS)

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
		_set_input(workflow, "129", "noise_seed", seed)
		_set_input(workflow, "132", "value", max(5, frame_count / 24))
		_set_input(workflow, "136", "width", width)
		_set_input(workflow, "136", "height", height)
		_set_input(workflow, "92", "filename_prefix", output_prefix)
		return workflow


def _set_input(workflow, node_key, input_name, value):
	node = workflow.get(node_key)
	inputs = node.get("inputs") if isinstance(node, dict) else None
	if not isinstance(inputs, dict) or input_name not in inputs:
		raise ValueError(
			f"MiniMax H3 API workflow is missing execution input {node_key}.{input_name}"
		)
	inputs[input_name] = value
