import frappe

from .register_minimax_h3_workflows import _register_workflow


GENERATION = {
	"filename": "minimax_h3_sato_generation.json",
	"workflow_key": "h3_sato_generation",
	"adapter_key": "minimax_h3_sato_generation",
	"bindings": (
		{
			"binding_key": "generation_prompt",
			"node_key": "270",
			"input_name": "prompt",
			"value_type": "Text",
			"required": 1,
		},
		{
			"binding_key": "first_frame",
			"node_key": "214",
			"input_name": "image",
			"required_input_role": "first_frame",
			"value_type": "File Path",
			"required": 1,
			"accepted_media_type": "Image",
		},
	),
}

CONTINUATION = {
	"filename": "minimax_h3_sato_continuation.json",
	"workflow_key": "h3_sato_continuation",
	"adapter_key": "minimax_h3_sato_continuation",
	"bindings": (
		{
			"binding_key": "generation_prompt",
			"node_key": "328",
			"input_name": "prompt",
			"value_type": "Text",
			"required": 1,
		},
		{
			"binding_key": "seed_video",
			"node_key": "264",
			"input_name": "file",
			"required_input_role": "seed_video",
			"value_type": "File Path",
			"required": 1,
			"accepted_media_type": "Video",
		},
		{
			"binding_key": "continuation_state",
			"node_key": "356",
			"input_name": "latent_file",
			"required_input_role": "continuation_state",
			"value_type": "File Path",
			"required": 1,
		},
	),
}


def execute():
	generation_name = _register_workflow(GENERATION)
	continuation_name = _register_workflow(CONTINUATION)
	if not frappe.db.get_value("Generation Workflow", generation_name, "continuation_workflow"):
		frappe.db.set_value(
			"Generation Workflow", generation_name, "continuation_workflow", continuation_name
		)
