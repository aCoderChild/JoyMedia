import json


def canonical_workflow_json(workflow_data):
	return json.dumps(workflow_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class GenericWorkflowAdapter:
	"""Default adapter for workflow families without model-specific metadata extraction."""

	def extract_execution_metadata(self, workflow_data):
		return {}

	def compile_prompt(self, shot, media_spec):
		return (getattr(shot, "generation_prompt", None) or "").strip()

	def finalize_workflow(self, workflow, workflow_version, staged_inputs):
		return workflow

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
		return workflow

	@staticmethod
	def get_value(data, path):
		if not path:
			return None
		for key in path:
			if not isinstance(data, dict) or key not in data:
				return None
			data = data[key]
		return data
