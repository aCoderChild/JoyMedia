import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.prompt_compiler import (
	_build_source_snapshot, compile_prompt_for_documents, segment_action_timing_instruction,
)
from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter


class TestPromptCompiler(FrappeTestCase):
	def test_segment_timing_contract_is_model_agnostic(self):
		instruction = segment_action_timing_instruction()
		self.assertIn("seconds-based", instruction)
		self.assertNotIn("frame 110", instruction)
		self.assertEqual(instruction, segment_action_timing_instruction())

	def test_source_snapshot_uses_current_media_and_shot_fields(self):
		project = frappe._dict(
			name="PROJECT-TEST",
			generation_mode="Multi-shot",
			global_instructions="",
		)
		shot = frappe._dict(
			name="SHOT-TEST",
			generation_prompt="A premium bottle reveal with a slow dolly-in.",
		)

		snapshot = _build_source_snapshot(shot, project)

		self.assertEqual(
			{
				"media_project": "PROJECT-TEST",
				"shot": "SHOT-TEST",
				"generation_prompt": "A premium bottle reveal with a slow dolly-in.",
				"image_prompt": "",
				"motion_plan_json": "",
				"start_state": "",
				"end_state": "",
				"handoff_type": "",
				"global_instructions": "",
			},
			snapshot,
		)
		self.assertNotIn("required_elements", snapshot)

		prompt = GenericComfyUIAdapter().compile_prompt(shot, project)

		self.assertEqual(prompt, "A premium bottle reveal with a slow dolly-in.")

	def test_scene_description_is_compiled_for_image_and_motion(self):
		project = frappe._dict(generation_mode="Continuous", global_instructions="")
		shot = frappe._dict(
			name="SHOT-TEST", shot_number=1, generation_prompt="The hand lifts the bottle toward camera.",
			image_prompt="Compose the bottle on a marble table.",
			motion_plan_json='{"actions":[{"start":0,"end":4,"action":"lift the bottle"},{"start":4,"end":5,"action":"hold the pose"}]}',
			end_state="bottle held toward camera", handoff_type="pose_transition",
		)
		image = compile_prompt_for_documents(shot, project, prompt_source="image")
		motion = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertEqual(image, "The hand lifts the bottle toward camera.")
		self.assertIn("The hand lifts the bottle", motion)
		self.assertIn("0-4s: lift the bottle", motion)
