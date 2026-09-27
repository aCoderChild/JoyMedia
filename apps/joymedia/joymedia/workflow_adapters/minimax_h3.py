from .base import GenericWorkflowAdapter


H3_DEFAULTS = {
	"output_fps": 24,
	"frame_count": 124,
	"produces_video": 1,
	"produces_audio": 1,
}

H3_VALUE_PATHS = {
	"frame_count": ("minimax_cond", "inputs", "length"),
	"output_fps": ("save_video", "inputs", "frame_rate"),
}


class MiniMaxH3WorkflowAdapter(GenericWorkflowAdapter):
	"""Extract MiniMax H3 execution characteristics from its known ComfyUI nodes."""

	def compile_prompt(self, shot, media_spec):
		return super().compile_prompt(shot, media_spec)

	def finalize_workflow(self, workflow, workflow_version, staged_inputs):
		if staged_inputs.get("last_frame"):
			return workflow

		last_frame_binding = next(
			(
				binding
				for binding in workflow_version.bindings
				if binding.binding_key == "last_frame"
			),
			None,
		)
		if not last_frame_binding:
			return workflow

		loader_node_key = str(last_frame_binding.node_key)
		if loader_node_key == "minimax_cond":
			workflow["minimax_cond"]["inputs"]["last_frame"] = None
			return workflow

		pending = [loader_node_key]
		removed = set()
		while pending:
			source_node_key = pending.pop()
			if source_node_key in removed:
				continue

			for node_key, node in list(workflow.items()):
				if node_key in removed or node_key == source_node_key:
					continue
				inputs = node.get("inputs") or {}
				for input_name, value in list(inputs.items()):
					if not _references_node(value, source_node_key):
						continue
					if node_key == "minimax_cond" and input_name == "last_frame":
						inputs[input_name] = None
					else:
						pending.append(str(node_key))
					break

			removed.add(source_node_key)
			workflow.pop(source_node_key, None)

		if "minimax_cond" in workflow:
			workflow["minimax_cond"].setdefault("inputs", {})["last_frame"] = None
		return workflow

	def extract_execution_metadata(self, workflow_data):
		metadata = {}
		for fieldname, default in H3_DEFAULTS.items():
			value = self.get_value(workflow_data, H3_VALUE_PATHS.get(fieldname, ()))
			metadata[fieldname] = default if value is None else value
		return metadata


def _references_node(value, node_key):
	return isinstance(value, (list, tuple)) and value and str(value[0]) == node_key
