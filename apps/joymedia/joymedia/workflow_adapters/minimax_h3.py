from .base import GenericWorkflowAdapter


H3_DEFAULTS = {
	"execution_width": 1344,
	"execution_height": 768,
	"output_fps": 24,
	"frame_count": 124,
	"produces_video": 1,
	"produces_audio": 1,
}

H3_VALUE_PATHS = {
	"execution_width": ("minimax_cond", "inputs", "width"),
	"execution_height": ("minimax_cond", "inputs", "height"),
	"frame_count": ("minimax_cond", "inputs", "length"),
	"output_fps": ("save_video", "inputs", "frame_rate"),
}


class MiniMaxH3WorkflowAdapter(GenericWorkflowAdapter):
	"""Extract MiniMax H3 execution characteristics from its known ComfyUI nodes."""

	def extract_execution_metadata(self, workflow_data):
		metadata = {}
		for fieldname, default in H3_DEFAULTS.items():
			value = self.get_value(workflow_data, H3_VALUE_PATHS.get(fieldname, ()))
			metadata[fieldname] = default if value is None else value
		return metadata
