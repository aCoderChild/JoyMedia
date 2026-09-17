import json


def canonical_workflow_json(workflow_data):
	return json.dumps(workflow_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class GenericWorkflowAdapter:
	"""Default adapter for workflow families without model-specific metadata extraction."""

	def extract_execution_metadata(self, workflow_data):
		return {}

	@staticmethod
	def get_value(data, path):
		if not path:
			return None
		for key in path:
			if not isinstance(data, dict) or key not in data:
				return None
			data = data[key]
		return data
