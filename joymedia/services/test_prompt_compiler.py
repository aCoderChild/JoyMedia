import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.prompt_compiler import (
	_build_source_snapshot, compile_prompt_for_documents, compile_segment_prompt_from_snapshot, segment_action_timing_instruction,
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

	def test_image_and_motion_stages_compile_their_own_prompts(self):
		project = frappe._dict(generation_mode="Continuous", global_instructions="")
		shot = frappe._dict(
			name="SHOT-TEST", shot_number=1, generation_prompt="The hand lifts the bottle toward camera.",
			image_prompt="Compose the bottle on a marble table.",
			motion_plan_json='{"actions":[{"start":0,"end":4,"action":"lift the bottle"},{"start":4,"end":5,"action":"hold the pose"}]}',
			end_state="bottle held toward camera", handoff_type="pose_transition",
		)
		image = compile_prompt_for_documents(shot, project, prompt_source="image")
		motion = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertEqual(image, "Compose the bottle on a marble table.")
		self.assertIn("The hand lifts the bottle", motion)
		self.assertNotIn("Compose the bottle on a marble table.", motion)
		self.assertIn("0-4s: lift the bottle", motion)

	def test_referenced_product_prompts_require_fidelity(self):
		project = frappe._dict(generation_mode="Multi-shot", global_instructions="")
		shot = frappe._dict(
			name="SHOT-TEST", shot_number=1,
			generation_prompt="A presenter holds the product toward camera.",
			references=[{"reference_role": "product", "asset_version": "ASTV-TEST"}],
		)
		prompt = compile_prompt_for_documents(shot, project, prompt_source="motion")
		self.assertIn("market only the intended referenced product", prompt)
		self.assertIn("do not swap, merge, deform", prompt)

	def test_continuation_only_receives_its_own_action_window(self):
		project = frappe._dict(references=[], generation_mode="Multi-shot", global_instructions="")
		shot = frappe._dict(
			name="SHOT-TEST", shot_number=1, generation_prompt="A presenter tours the property.",
			motion_plan_json='{"actions":[{"start":0,"end":5,"action":"show the lobby"},{"start":5,"end":10,"action":"walk into the pool area"}]}',
			end_state="pool area visible", handoff_type="ending", references=[],
		)

		prompt = compile_segment_prompt_from_snapshot(
			shot, project, 2, 2, segment_start_frame=120, segment_effective_frames=120, fps=24, is_final=True,
		)

		self.assertIn("0-5s: walk into the pool area", prompt)
		self.assertNotIn("show the lobby", prompt)
