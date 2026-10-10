import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.prompt_compiler import _build_source_snapshot, segment_action_timing_instruction
from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter


class TestPromptCompiler(FrappeTestCase):
	def test_segment_timing_contract_is_deterministic(self):
		instruction = segment_action_timing_instruction()
		self.assertIn("by frame 110", instruction)
		self.assertIn("frames 111-124", instruction)
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
				"global_instructions": "",
			},
			snapshot,
		)
		self.assertNotIn("required_elements", snapshot)

		prompt = GenericComfyUIAdapter().compile_prompt(shot, project)

		self.assertEqual(prompt, "A premium bottle reveal with a slow dolly-in.")
