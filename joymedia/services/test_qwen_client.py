import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.qwen_client import _normalize_qwen_plan, _validate_video_plan


class TestQwenClient(FrappeTestCase):
	def test_text_model_prompt_only_output_does_not_invent_reference_assignments(self):
		plan = _normalize_qwen_plan(
			{
				"shots": [
					{"prompt": "A product hero reveal.", "duration_seconds": 2.5},
					{"video_prompt": "A slow closing detail shot.", "duration_seconds": 2.5},
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
		self.assertNotIn("first_frame_reference_image_index", plan["shots"][0])
		self.assertNotIn("last_frame_reference_image_index", plan["shots"][0])

	def test_continuous_mode_does_not_invent_reference_assignments(self):
		plan = _normalize_qwen_plan(
			{
				"shots": [
					{"generation_prompt": "Opening shot.", "duration_seconds": 2.5},
					{"generation_prompt": "Continuation.", "duration_seconds": 2.5},
				]
			},
			reference_image_count=1,
			generation_mode="Continuous",
		)

		_validate_video_plan(plan, reference_image_count=1, shot_count=2, generation_mode="Continuous")

		self.assertNotIn("reference_image_index", plan["shots"][0])
		self.assertNotIn("reference_image_index", plan["shots"][1])

	def test_semantic_shot_reference_usage_is_preserved(self):
		plan = _normalize_qwen_plan(
			{
				"shots": [{
					"shot_number": 1,
					"shot_name": "Hero reveal",
					"generation_prompt": "Reveal the product.",
					"duration_seconds": 5,
					"references": [
						{"reference_key": "hero_product", "usage_role": "product_reference"},
						{"reference_key": "camera_motion_01", "usage_role": "motion_reference"},
					],
				}],
			}
		)
		_validate_video_plan(plan)
		self.assertEqual(plan["shots"][0]["references"][0]["reference_key"], "hero_product")
		self.assertEqual(plan["shots"][0]["references"][1]["usage_role"], "motion_reference")
