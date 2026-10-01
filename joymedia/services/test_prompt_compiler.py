import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.prompt_compiler import _build_source_snapshot
from joymedia.workflow_adapters.minimax_h3 import MiniMaxH3WorkflowAdapter


class TestPromptCompiler(FrappeTestCase):
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
				"shot_specification": "SHOT-TEST",
				"generation_prompt": "A premium bottle reveal with a slow dolly-in.",
				"global_instructions": "",
			},
			snapshot,
		)
		self.assertNotIn("required_elements", snapshot)

		prompt = MiniMaxH3WorkflowAdapter().compile_prompt(shot, project)

		self.assertEqual(prompt, "A premium bottle reveal with a slow dolly-in.")
