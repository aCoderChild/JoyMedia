"""Opt-in upstream base image editing; retain the existing video workflow.

Comfy-Org/workflow_templates image_flux2_klein_image_edit_4b_base.json,
d0e41fe5423f93db5b5872cf273d7b1af8aa68bc. The graph keeps CFG=5,
20 Euler steps and reference latents on both conditioning branches. Shared
native image registration, role bindings and pipeline orchestration are reused.
Registration neither downloads weights nor promotes a deployment profile.
"""

import json

import frappe

from joymedia.patches.register_flux2_klein_pipeline import _register_keyframe
from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS, _pipeline_with


def register_image():
	return _register_keyframe(
		graph=GRAPHS / "flux2_klein_base_keyframe.json",
		spec=json.loads((GRAPHS / "flux2_klein_base_keyframe.execution.json").read_text()),
		workflow_key="flux2_klein_base_keyframe",
	)


def execute(video_workflow=None):
	from joymedia.services.workflows.pipeline import get_active_generation_pipeline

	video_workflow = video_workflow or get_active_generation_pipeline().steps[-1].workflow
	if frappe.db.get_value("Generation Workflow", video_workflow, "output_media_type") != "Video":
		raise ValueError("Choose an existing video-producing workflow for the base image stage.")
	image = register_image()
	pipeline = _pipeline_with(image, video_workflow)
	if not pipeline:
		pipeline = (
			frappe.get_doc(
				{
					"doctype": "Generation Pipeline",
					"pipeline_key": "reference_staging_base_image_video",
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
