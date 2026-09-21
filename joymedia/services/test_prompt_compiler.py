import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.prompt_compiler import _build_source_snapshot, _render_template


class TestPromptCompiler(FrappeTestCase):
	def test_source_snapshot_uses_current_media_and_shot_fields(self):
		media_specification = frappe._dict(
			name="SPEC-TEST",
			generation_instructions="Keep the product identity consistent.",
		)
		shot = frappe._dict(
			name="SHOT-TEST",
			camera_direction="Slow dolly-in.",
			subject_identity="Bottle on a marble surface.",
			action_plot="Condensation forms on the bottle.",
			environment="Warm backlight with soft shadows.",
			audio_direction="Soft glass movement and ambience.",
		)

		snapshot = _build_source_snapshot(shot, media_specification)

		self.assertEqual(
			{
				"media_specification": "SPEC-TEST",
				"shot_specification": "SHOT-TEST",
				"generation_instructions": "Keep the product identity consistent.",
				"camera_direction": "Slow dolly-in.",
				"subject_identity": "Bottle on a marble surface.",
				"action_plot": "Condensation forms on the bottle.",
				"environment": "Warm backlight with soft shadows.",
				"audio_direction": "Soft glass movement and ambience.",
			},
			snapshot,
		)
		self.assertNotIn("required_elements", snapshot)
		self.assertNotIn("spatial_composition", snapshot)

		prompt = _render_template(
			"[Camera]: {camera_direction}\n"
			"[Subject]: {subject_identity}\n"
			"[Motion]: {action_plot}\n"
			"[Lighting & Environment]: {environment}\n"
			"[Audio SFX]: {audio_direction}\n"
			"{generation_instructions}",
			snapshot,
		)

		self.assertIn("[Camera]: Slow dolly-in.", prompt)
		self.assertIn("[Audio SFX]: Soft glass movement and ambience.", prompt)
		self.assertIn("Keep the product identity consistent.", prompt)
