"""Register the upstream RefControl 4B depth workflow without promoting it.

The vendor workflow is thedeoxen/refcontrol-FLUX.2-klein-4B-reference-depth-lora
at 0ae1ef7f9acc4e55ec2237360943c3c3032d3583 (Apache-2.0). Our API graph
adapts its depth -> identity reference order to the existing Klein base 4B
multi-reference adapter. A *separate*, physically validated layout photograph
must be supplied as ``geometry_reference``; estimating depth from a frame with
bad support would simply preserve that error. This workflow is never selected
by the automatic pipeline merely because its weights are present.
"""

import json

import frappe

from joymedia.patches.register_flux2_klein_pipeline import _register_keyframe
from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS, _pipeline_with

WORKFLOW_KEY = "flux2_klein_4b_refcontrol_depth_keyframe"
GRAPH = GRAPHS / "flux2_klein_refcontrol_depth_keyframe.json"
SPEC = GRAPHS / "flux2_klein_refcontrol_depth_keyframe.execution.json"


def register_image():
	return _register_keyframe(
		graph=GRAPH,
		spec=json.loads(SPEC.read_text()),
		workflow_key=WORKFLOW_KEY,
		extra_bindings=(
			{
				"binding_key": "geometry_reference",
				"node_key": "geometry_image",
				"input_name": "image",
				"required_input_role": "geometry_reference",
				"value_type": "File Path",
				"required": 1,
				"accepted_media_type": "Image",
				"allow_multiple": 0,
			},
		),
	)


def execute(video_workflow=None):
	"""Register, but never promote, the depth-controlled image-to-video route.

	The route is selected only when an operator maps a promoted base pipeline to
	this validated sibling through ``joymedia_geometry_generation_pipelines``.
	Keeping registration and promotion separate avoids routing customer work to a
	graph whose LoRA or depth checkpoint is not installed yet.
	"""
	if not video_workflow:
		from joymedia.services.workflows.pipeline import get_active_generation_pipeline

		video_workflow = get_active_generation_pipeline().steps[-1].workflow
	if frappe.db.get_value("Generation Workflow", video_workflow, "output_media_type") != "Video":
		raise ValueError("Choose an existing video-producing workflow for the depth image stage.")
	image = register_image()
	pipeline = _pipeline_with(image, video_workflow)
	if not pipeline:
		pipeline = (
			frappe.get_doc(
				{
					"doctype": "Generation Pipeline",
					"pipeline_key": "reference_geometry_depth_image_video",
					"output_media_type": "Video",
					"steps": [
						{
							"step_key": "keyframe",
							"workflow": image,
							"prompt_source": "Image",
							"produces_artifact_role": "Primary Image",
						},
						{
							"step_key": "video",
							"workflow": video_workflow,
							"prompt_source": "Motion",
							"depends_on_step": "keyframe",
							"consumes_artifact_role": "Primary Image",
							"produces_artifact_role": "Primary Video",
						},
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return {"pipeline": pipeline, "image_workflow": image, "video_workflow": video_workflow}
