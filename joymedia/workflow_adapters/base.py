import json


def canonical_workflow_json(workflow_data):
	return json.dumps(workflow_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class GenericWorkflowAdapter:
	"""Default adapter for workflow families without model-specific metadata extraction."""

	def extract_execution_metadata(self, workflow_data):
		return {}

	def compile_prompt(self, shot, media_spec):
		return "\n".join(
			line.strip()
			for line in (
				"Camera & Framing:",
				shot.camera_direction or "",
				"Subject:",
				shot.subject_identity or "",
				"Motion:",
				shot.action_plot or "",
				"Lighting & Environment:",
				shot.environment or "",
				"Audio:",
				shot.audio_direction or "",
				"Global Instructions:",
				media_spec.generation_instructions or "",
			)
			if line.strip()
		)

	def finalize_workflow(self, workflow, workflow_version, staged_inputs):
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
