"""Register an opt-in Klein base-4B RefControl pose workflow.

The pose LoRA is from xocialize/refcontrol-FLUX.2-klein-4B-pose-lora
(Apache-2.0). The guide is reference image 1 and the character identity is
reference image 2. Registration does not alter the production pipeline.
"""

import json

from joymedia.patches.register_flux2_klein_pipeline import _register_keyframe
from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS

WORKFLOW_KEY = "flux2_klein_4b_refcontrol_pose_keyframe"
GRAPH = GRAPHS / "flux2_klein_refcontrol_pose_keyframe.json"
SPEC = GRAPHS / "flux2_klein_refcontrol_pose_keyframe.execution.json"


def register_image():
	return _register_keyframe(
		graph=GRAPH,
		spec=json.loads(SPEC.read_text()),
		workflow_key=WORKFLOW_KEY,
		extra_bindings=(
			{
				"binding_key": "pose_guide",
				"node_key": "geometry_image",
				"input_name": "image",
				"required_input_role": "pose_guide",
				"value_type": "File Path",
				"required": 1,
				"accepted_media_type": "Image",
				"allow_multiple": 0,
			},
		),
	)
