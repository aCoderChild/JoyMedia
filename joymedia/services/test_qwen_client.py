import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.qwen_client import _normalize_qwen_plan, _validate_video_plan


class TestQwenClient(FrappeTestCase):
	def test_equal_image_and_shot_counts_assign_images_in_order_for_single_image_workflows(self):
		contract = [{
			"role": "first_frame",
			"min_count": 1,
			"max_count": 1,
			"accepted_media_type": "Image",
			"allow_multiple": False,
		}]
		plan = _normalize_qwen_plan(
			{
				"shots": [
					{"generation_prompt": "Exterior.", "duration_seconds": 5},
					{"generation_prompt": "Pool.", "duration_seconds": 5},
				]
			},
			reference_image_count=2,
			generation_mode="Multi-shot",
			reference_images=[
				{"reference_key": "property_1"},
				{"reference_key": "property_2"},
			],
			workflow_input_contract=contract,
		)

		self.assertEqual(
			[
				{"reference_key": "property_1", "usage_role": "first_frame"},
			],
			plan["shots"][0]["references"],
		)
		self.assertEqual(
			[
				{"reference_key": "property_2", "usage_role": "first_frame"},
			],
			plan["shots"][1]["references"],
		)

	def test_multi_reference_workflow_fills_missing_r2v_slots_from_selected_pool(self):
		contract = [{
			"role": "product_reference",
			"min_count": 2,
			"max_count": 2,
			"accepted_media_type": "Image",
			"allow_multiple": True,
		}]
		plan = _normalize_qwen_plan(
			{
				"shots": [{
					"shot_number": 2,
					"generation_prompt": "Show the product.",
					"duration_seconds": 5,
					"references": [{"reference_key": "dress", "usage_role": "product_reference"}],
				}],
			},
			reference_images=[{"reference_key": "dress"}, {"reference_key": "model"}],
			workflow_input_contract=contract,
		)

		_validate_video_plan(plan, workflow_input_contract=contract)
		self.assertEqual(
			[
				{"reference_key": "dress", "usage_role": "product_reference"},
				{"reference_key": "model", "usage_role": "product_reference"},
			],
			plan["shots"][0]["references"],
		)

	def test_pipeline_reference_role_preserves_multiple_references_for_keyframe_stage(self):
		contract = [{
			"role": "keyframe_reference",
			"min_count": 1,
			"max_count": 0,
			"accepted_media_type": "Image",
			"allow_multiple": True,
		}]
		plan = _normalize_qwen_plan(
			{
				"shots": [{
					"generation_prompt": "Show the product.",
					"duration_seconds": 5,
					"references": [
						{"reference_key": "talent", "usage_role": "keyframe_reference"},
						{"reference_key": "product", "usage_role": "keyframe_reference"},
					],
				}],
			},
			workflow_input_contract=contract,
		)

		_validate_video_plan(plan, workflow_input_contract=contract)
		self.assertEqual(2, len(plan["shots"][0]["references"]))
	def test_equal_image_and_shot_counts_use_equal_total_duration(self):
		plan = _normalize_qwen_plan(
			{
				"shots": [
					{"generation_prompt": "Exterior.", "duration_seconds": 20},
					{"generation_prompt": "Pool.", "duration_seconds": 1},
				]
			},
			reference_image_count=2,
			generation_mode="Multi-shot",
			reference_images=[
				{"reference_key": "property_1"},
				{"reference_key": "property_2"},
			],
			total_video_duration=45,
		)

		self.assertEqual([22.5, 22.5], [shot["duration_seconds"] for shot in plan["shots"]])

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

	def test_continuous_mode_requires_static_first_frame_only_for_shot_one(self):
		contract = [{
			"role": "first_frame",
			"min_count": 1,
			"max_count": 1,
			"accepted_media_type": "Image",
			"allow_multiple": False,
		}]
		plan = _normalize_qwen_plan(
			{
				"shots": [
					{
						"shot_number": 1,
						"generation_prompt": "Opening shot.",
						"duration_seconds": 2.5,
						"references": [{"reference_key": "hero", "usage_role": "first_frame"}],
					},
					{
						"shot_number": 2,
						"generation_prompt": "Continue the movement.",
						"duration_seconds": 2.5,
					},
				],
			},
			workflow_input_contract=contract,
			generation_mode="Continuous",
		)

		_validate_video_plan(plan, workflow_input_contract=contract, generation_mode="Continuous")

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
						{"reference_key": "hero_product_side", "usage_role": "product_reference"},
					],
				}],
			}
		)
		_validate_video_plan(plan)
		self.assertEqual(plan["shots"][0]["references"][0]["reference_key"], "hero_product")
		self.assertEqual(plan["shots"][0]["references"][1]["usage_role"], "product_reference")

	def test_workflow_contract_rejects_unsupported_or_repeated_roles(self):
		contract = [{
			"role": "product_reference",
			"value_type": "File Path",
			"required": False,
			"accepted_media_type": "Image",
			"allow_multiple": False,
		}]
		plan = _normalize_qwen_plan({
			"shots": [{
				"shot_number": 1,
				"generation_prompt": "Show the product.",
				"duration_seconds": 2,
				"references": [
					{"reference_key": "one", "usage_role": "product_reference"},
					{"reference_key": "two", "usage_role": "product_reference"},
				],
			}],
		})
		with self.assertRaises(frappe.ValidationError):
			_validate_video_plan(plan, workflow_input_contract=contract)

	def test_validation_rescales_multi_shot_durations_to_total(self):
		result = {"shots": [
			{"shot_number": 1, "generation_prompt": "Exterior.", "duration_seconds": 2},
			{"shot_number": 2, "generation_prompt": "Pool.", "duration_seconds": 6},
		]}

		_validate_video_plan(result, generation_mode="Multi-shot", total_video_duration=16)

		self.assertEqual([4, 12], [shot["duration_seconds"] for shot in result["shots"]])
