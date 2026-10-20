"""Opt-in install script (not run by migrate): register the video-to-audio sound-effects workflow.

The graph is the ComfyUI-MMAudio extension's shipped template with the model files
installed on this server. It listens to a clip and a text prompt and returns audio
(effects and ambience, not speech). Registration creates an immutable workflow version.
"""

import json
from pathlib import Path

import frappe

WORKFLOW_KEY = "mmaudio_video_to_audio"
GRAPH = (
	Path(__file__).resolve().parent.parent / "workflow_adapters" / "graphs" / "mmaudio_video_to_audio.json"
)


def execute():
	name = frappe.db.get_value(
		"Generation Workflow", {"workflow_key": WORKFLOW_KEY}, "name", order_by="version_number desc"
	)
	if name and json.loads(frappe.db.get_value("Generation Workflow", name, "workflow_json")) == json.loads(
		GRAPH.read_text()
	):
		return name
	spec = {
		"parameters": [
			{"semantic": "seed", "node_key": "92", "input_name": "seed"},
			{
				"semantic": "frame_count",
				"node_key": "92",
				"input_name": "duration",
				"transform": "frames_to_seconds",
				"fps": 24,
			},
			{"semantic": "output_prefix", "node_key": "98", "input_name": "filename_prefix"},
		],
		"outputs": {"primary": {"node_key": "98", "media_type": "Audio"}},
		# MMAudio is trained on clips of about 8 seconds.
		"metadata": {"frame_count": 192, "output_fps": 24, "produces_video": 0, "produces_audio": 1},
	}
	doc = frappe.get_doc(
		{
			"doctype": "Generation Workflow",
			"workflow_key": WORKFLOW_KEY,
			"adapter_key": "comfyui_generic",
			"workflow_json": GRAPH.read_text(),
			"execution_spec": json.dumps(spec),
		}
	)
	doc.append(
		"bindings",
		{
			"binding_key": "generation_prompt",
			"node_key": "92",
			"input_name": "prompt",
			"value_type": "Text",
			"required": 1,
		},
	)
	doc.append(
		"bindings",
		{
			"binding_key": "source_video",
			"node_key": "91",
			"input_name": "video",
			"required_input_role": "source_video",
			"value_type": "File Path",
			"required": 1,
			"accepted_media_type": "Video",
			"allow_multiple": 0,
		},
	)
	doc.insert(ignore_permissions=True)
	return doc.name
