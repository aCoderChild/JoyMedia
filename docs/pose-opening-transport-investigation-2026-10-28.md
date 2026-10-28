# Opening-pose and transport investigation, 28 October 2026

The GPU demo batch CRB-00002 reached Needs Attention because the required pose views for seven scenes were not qualified. No first-frame generation run was created. Existing RefControl tests distorted the mascot, so enabling it alone is not evidence of a solution.

The pose planner prompt formerly demanded action gestures even when they occur after the opening frame. The updated prompt distinguishes a gesture already present at the opening from one that starts during the shot; explicit opening gestures and the existing pose and physical admission checks remain required. This is a prompt correction, not evidence that the planner obeys it in live inference.

Cora was cloned for research at `/workspace/development/research/cora-pose-edit`, revision 722d71d. Its implementation loads SDXL Turbo through Diffusers; it is not a drop-in for the installed ComfyUI FLUX/H3 graph. Its identity and pose quality have not been verified here, so it was not installed into production or used to approve any images.

A separate experiment PRJ-02721 was created from PRJ-02695. The storyboard was approved solely for this test and first frame SHOT-02964 submitted through the Frappe generation service as RUN-01339 / TASK-02631 / ATT-02484. Frappe prepared the task, but the attempt had no ComfyUI prompt ID at inspection. The configured 18188 transfer endpoint timed out on a health request while the 18189 control endpoint and 8188 responded. This is evidence of a transfer-path problem, not a completed inference test. The test did not use a browser and does not verify the automatic reference-to-video pipeline.
