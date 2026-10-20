"""Register a text-only instrumental music workflow, separate from video foley."""

import json

import frappe

from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS

WORKFLOW_KEY = "mmaudio_bgm"
GRAPH = GRAPHS / "mmaudio_bgm.json"


def execution_spec():
	return {
		"capabilities": ["music", "text_to_audio"],
		"limits": {"max_frames": 744},
		"parameters": [
			{"semantic": "seed", "node_key": "music", "input_name": "seed"},
			{"semantic": "frame_count", "node_key": "music", "input_name": "duration", "transform": "frames_to_seconds", "fps": 24},
			{"semantic": "output_prefix", "node_key": "save", "input_name": "filename_prefix"},
		],
		"outputs": {"primary": {"node_key": "save", "media_type": "Audio"}},
		"metadata": {"frame_count": 192, "output_fps": 24, "produces_video": 0, "produces_audio": 1},
	}


def execute():
	graph, spec = json.loads(GRAPH.read_text()), execution_spec()
	name = frappe.db.get_value("Generation Workflow", {"workflow_key": WORKFLOW_KEY}, "name", order_by="version_number desc")
	if name:
		stored = frappe.db.get_value("Generation Workflow", name, ["workflow_json", "execution_spec"], as_dict=True)
		if json.loads(stored.workflow_json) == graph and json.loads(stored.execution_spec) == spec:
			return name
	doc = frappe.get_doc({
		"doctype": "Generation Workflow", "workflow_key": WORKFLOW_KEY, "adapter_key": "comfyui_generic",
		"workflow_json": json.dumps(graph), "execution_spec": json.dumps(spec),
		"bindings": [{"binding_key": "generation_prompt", "node_key": "music", "input_name": "prompt", "value_type": "Text", "required": 1}],
	}).insert(ignore_permissions=True)
	return doc.name
