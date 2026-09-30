import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.qwen_client import _normalize_qwen_plan, _validate_video_plan


class TestQwenClient(FrappeTestCase):
	def test_text_model_prompt_only_output_is_normalized(self):
		plan = _normalize_qwen_plan(
			{
				"shots": [
					{"prompt": "A product hero reveal."},
					{"video_prompt": "A slow closing detail shot."},
				]
			},
			reference_image_count=2,
			generation_mode="Multi-shot",
		)

		_validate_video_plan(plan, reference_image_count=2, shot_count=2, generation_mode="Multi-shot")

		self.assertEqual(plan["shots"][0]["shot_number"], 1)
		self.assertEqual(plan["shots"][0]["generation_prompt"], "A product hero reveal.")
		self.assertEqual(plan["shots"][0]["shot_name"], "Shot 1")
		self.assertNotIn("subject", plan["shots"][0])
		self.assertNotIn("camera", plan["shots"][0])
		self.assertNotIn("lighting", plan["shots"][0])
		self.assertEqual(plan["shots"][0]["first_frame_reference_image_index"], 1)
		self.assertEqual(plan["shots"][0]["last_frame_reference_image_index"], 2)
		self.assertEqual(plan["shots"][1]["first_frame_reference_image_index"], 2)

	def test_continuous_mode_assigns_only_the_first_reference(self):
		plan = _normalize_qwen_plan(
			{"shots": [{"generation_prompt": "Opening shot."}, {"generation_prompt": "Continuation."}]},
			reference_image_count=1,
			generation_mode="Continuous",
		)

		_validate_video_plan(plan, reference_image_count=1, shot_count=2, generation_mode="Continuous")

		self.assertEqual(plan["shots"][0]["reference_image_index"], 1)
		self.assertNotIn("reference_image_index", plan["shots"][1])
