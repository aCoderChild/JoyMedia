from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import film_director, qwen_client, vision_analysis
from joymedia.services.prompt_compiler import compile_segment_prompt_from_snapshot


R2V_CONTRACT = [{
	"role": "product_reference",
	"value_type": "File Path",
	"required": True,
	"accepted_media_type": "Image",
	"allow_multiple": True,
	"min_count": 2,
	"max_count": 2,
}]

REFERENCES = [
	{"reference_key": "model", "media_type": "Image", "asset_category": "Character", "reference_role": "Product", "asset_name": "model"},
	{"reference_key": "tower", "media_type": "Image", "asset_category": "Product", "reference_role": "Product", "asset_name": "tower",
	 "analysis": {"kind": "place", "description": "Cream high-rise tower at golden hour"}},
	{"reference_key": "bedroom", "media_type": "Image", "asset_category": "Background", "reference_role": "Product", "asset_name": "bedroom"},
	{"reference_key": "logo", "media_type": "Image", "asset_category": "Brand", "reference_role": "Product", "asset_name": "logo"},
]


def _response(payload, ok=True):
	response = MagicMock(ok=ok)
	response.json.return_value = payload
	return response


class TestFilmDirector(FrappeTestCase):
	def test_roster_uses_analysis_category_and_role(self):
		roster = film_director.build_roster(REFERENCES)

		self.assertEqual(["model"], [item["reference_key"] for item in roster[film_director.CHARACTER]])
		self.assertEqual(["tower", "bedroom"], [item["reference_key"] for item in roster[film_director.PLACE]])
		self.assertTrue(film_director.is_story_film(REFERENCES))
		self.assertFalse(film_director.is_story_film(REFERENCES[1:]))

	def test_person_analysis_overrides_product_category(self):
		context = {"media_type": "Image", "asset_category": "Product", "analysis": {"kind": "person"}}

		self.assertEqual(film_director.CHARACTER, film_director.classify_reference(context))

	def test_takes_with_a_person_get_character_then_described_place(self):
		shots = [
			# The planner listed the place first and the character second.
			{"generation_prompt": "She turns on the bedroom balcony.",
			 "references": [{"reference_key": "bedroom"}, {"reference_key": "model"}]},
			# The planner omitted the character although the prompt shows her.
			{"generation_prompt": "The woman walks past the cream high-rise tower at golden hour.",
			 "references": [{"reference_key": "bedroom"}, {"reference_key": "tower"}]},
			# No references at all: the place is chosen from the prompt text.
			{"generation_prompt": "She relaxes in the bedroom.", "references": []},
		]

		film_director.normalize_story_references(shots, REFERENCES, "product_reference")

		self.assertEqual(
			[["model", "bedroom"], ["model", "tower"], ["model", "bedroom"]],
			[[ref["reference_key"] for ref in shot["references"]] for shot in shots],
		)
		self.assertTrue(all(
			ref["usage_role"] == "product_reference" for shot in shots for ref in shot["references"]
		))

	def test_takes_without_a_person_put_the_described_place_second(self):
		shots = [{
			"generation_prompt": "Rising aerial over the cream high-rise tower at golden hour.",
			"references": [{"reference_key": "tower"}, {"reference_key": "bedroom"}],
		}]

		film_director.normalize_story_references(shots, REFERENCES, "product_reference")

		self.assertEqual(["bedroom", "tower"], [ref["reference_key"] for ref in shots[0]["references"]])

	def test_tags_beyond_the_sent_images_point_at_the_place(self):
		# Planners confuse place keys named "3"/"4" with picture numbers.
		shots = [{"generation_prompt": "The person from <Picture 1> walks through the place from <Picture 4>.",
		          "references": [{"reference_key": "model"}, {"reference_key": "bedroom"}]}]

		film_director.normalize_story_references(shots, REFERENCES, "product_reference")

		self.assertEqual(
			"The person from <Picture 1> walks through the place from <Picture 2>.",
			shots[0]["generation_prompt"],
		)

	def test_roster_flags_images_without_a_description(self):
		references = [
			{"reference_key": "3", "media_type": "Image", "asset_category": "Background", "asset_name": "3"},
			{"reference_key": "lobby", "media_type": "Image", "asset_category": "Background", "asset_name": "lobby"},
		]

		self.assertEqual("- key=3: (no visual description available)", film_director._roster_line(references[0]))
		self.assertEqual("- key=lobby: lobby (no visual description available)", film_director._roster_line(references[1]))

	def test_director_instruction_lists_roster_and_role(self):
		instruction = film_director.build_director_instruction(REFERENCES, "product_reference", 25)

		self.assertIn('usage_role "product_reference"', instruction)
		self.assertIn("key=model", instruction)
		self.assertIn("key=tower: Cream high-rise tower at golden hour", instruction)
		self.assertNotIn("key=logo", instruction)
		self.assertIn("<Picture 1>", instruction)
		self.assertIn("Plan 3 to 5 long continuous takes", instruction)
		fixed_text = (film_director.DIRECTOR_RULES + film_director.FEW_SHOT_EXAMPLE).lower()
		for genre_specific in ("real-estate", "property", "golden hour", "teal", "ao dai", "luxury"):
			self.assertNotIn(genre_specific, fixed_text)

	def test_take_count_keeps_every_take_within_model_range(self):
		self.assertEqual((2, 3), film_director.take_count_range(15))
		self.assertEqual((3, 5), film_director.take_count_range(25))
		self.assertEqual((6, 6), film_director.take_count_range(60))
		self.assertEqual((2, 2), film_director.take_count_range(5))

	def test_take_durations_are_renderable_and_keep_the_total(self):
		shots = [{"duration_seconds": value, "shot_number": index} for index, value in enumerate((12.33, 3.42, 5.08, 4.17), 1)]

		balanced = film_director.balance_take_durations(shots, 25)

		durations = [shot["duration_seconds"] for shot in balanced]
		self.assertAlmostEqual(25, sum(durations), places=6)
		self.assertTrue(all(film_director.MIN_RENDER_SECONDS - 1e-6 <= value <= 10 + 1e-6 for value in durations))
		self.assertGreater(durations[0], durations[1])

	def test_too_many_takes_for_the_total_drops_short_middle_takes(self):
		shots = [{"duration_seconds": value, "shot_number": index} for index, value in enumerate((4, 1, 3, 4), 1)]

		balanced = film_director.balance_take_durations(shots, 12)

		self.assertEqual([1, 2], [shot["shot_number"] for shot in balanced])
		self.assertAlmostEqual(12, sum(shot["duration_seconds"] for shot in balanced))

	def test_product_words_are_not_mistaken_for_the_character(self):
		shots = [{
			"generation_prompt": "Slow orbit around the new car model parked in the tower driveway; no extra people.",
			"references": [{"reference_key": "tower"}],
		}]

		film_director.normalize_story_references(shots, REFERENCES, "product_reference")

		self.assertEqual(["bedroom", "tower"], [ref["reference_key"] for ref in shots[0]["references"]])

	def test_story_film_plan_uses_director_prompt_and_orders_references(self):
		plan = {"shots": [
			{"shot_number": 1, "duration_seconds": 8, "generation_prompt": "She smiles at the cream high-rise tower.",
			 "references": [{"reference_key": "tower", "usage_role": "product_reference"},
			                {"reference_key": "model", "usage_role": "product_reference"}]},
			{"shot_number": 2, "duration_seconds": 7, "generation_prompt": "She wakes in the bedroom.",
			 "references": [{"reference_key": "bedroom", "usage_role": "product_reference"}]},
		]}
		sent = {}

		def fake_post(url, json=None, timeout=None):
			if url.endswith("/tokenize"):
				return _response({"count": 900, "max_model_len": 4096})
			sent["payload"] = json
			return _response({"choices": [{"message": {"content": frappe.as_json(plan)}}]})

		with (
			patch.object(qwen_client, "_qwen_config", return_value=("http://qwen/v1", "planner", 30)),
			patch.object(qwen_client.requests, "post", side_effect=fake_post),
		):
			result = qwen_client.generate_video_plan(
				product_name="Riviera Point",
				video_idea="Lifestyle film",
				total_video_duration=15,
				target_fps=24,
				reference_media=REFERENCES,
				reference_images=[{"index": 1, "reference_key": "model", "asset_name": "model"}],
				generation_mode="Multi-shot",
				workflow_input_contract=R2V_CONTRACT,
				story_film=True,
			)

		prompt = sent["payload"]["messages"][1]["content"]
		self.assertIn("film director", prompt)
		self.assertIn("Return 2 to 3 takes as shots.", prompt)
		self.assertNotIn("AVAILABLE INPUT ROLES", prompt)
		self.assertNotIn("GENERATION IMAGE REFERENCES", prompt)
		self.assertEqual(3000, sent["payload"]["max_tokens"])
		self.assertEqual(
			[["model", "tower"], ["model", "bedroom"]],
			[[ref["reference_key"] for ref in shot["references"]] for shot in result["shots"]],
		)
		self.assertAlmostEqual(15, sum(shot["duration_seconds"] for shot in result["shots"]))

	def test_completion_budget_fits_context_window(self):
		payload = {"model": "planner", "messages": [{"role": "user", "content": "x"}], "max_tokens": 3000}

		with patch.object(qwen_client.requests, "post", return_value=_response({"count": 1500, "max_model_len": 4096})):
			self.assertEqual(4096 - 1500 - 64, qwen_client._completion_budget("http://qwen/v1", payload))

		with patch.object(qwen_client.requests, "post", return_value=_response({"count": 3500, "max_model_len": 4096})):
			with self.assertRaises(frappe.ValidationError):
				qwen_client._completion_budget("http://qwen/v1", payload)

	def test_completion_budget_estimates_without_tokenize_endpoint(self):
		payload = {"model": "planner", "messages": [{"role": "user", "content": "x" * 300}], "max_tokens": 3000}

		with (
			patch.object(qwen_client.requests, "post", side_effect=qwen_client.requests.ConnectionError()),
			patch.dict(frappe.conf, {"qwen_max_model_len": 16384}),
		):
			self.assertEqual(3000, qwen_client._completion_budget("http://qwen/v1", payload))

	def _snapshot(self, reference_mode="Multi-reference"):
		return frappe._dict({
			"reference_mode": reference_mode,
			"global_instructions": "Tour the tower, the pool and the lobby.",
			"references": [
				{"asset_version": "AV-MODEL", "reference_role": "Character", "label": ""},
				{"asset_version": "AV-ROOM", "reference_role": "Environment", "label": "bedroom"},
			],
			"shots": [{"shot": "SHOT-1", "references": [
				{"reference_role": "product_reference", "asset_version": "AV-MODEL"},
				{"reference_role": "product_reference", "asset_version": "AV-ROOM"},
			]}],
		})

	def _compile(self, snapshot, segment_index=1, segment_count=1):
		shot = frappe._dict(name="SHOT-1", shot_number=1,
		                    generation_prompt="The person from <Picture 1> rests in the place from <Picture 2>.")
		with patch.object(
			film_director,
			"_asset_version_context",
			side_effect=lambda version, reference: {
				"media_type": "Image", "reference_role": reference.get("reference_role"), "analysis": {},
			},
		):
			return compile_segment_prompt_from_snapshot(shot, snapshot, segment_index, segment_count)

	def test_reference_take_prompt_names_pictures_and_skips_the_film_brief(self):
		prompt = self._compile(self._snapshot())

		self.assertTrue(prompt.startswith("<Picture 1> is the main character"))
		self.assertIn("<Picture 2> is the location (bedroom)", prompt)
		# The planner already used the brief; repeating it turns one take into a montage.
		self.assertNotIn("Tour the tower", prompt)

	def test_continuation_prompt_has_no_picture_tags(self):
		prompt = self._compile(self._snapshot(), segment_index=2, segment_count=2)

		self.assertNotIn("<Picture", prompt)
		self.assertIn("The person from the earlier frames rests in the place from the earlier frames.", prompt)

	def test_single_image_prompt_keeps_global_instructions(self):
		prompt = self._compile(self._snapshot("Single Image"))

		self.assertNotIn("is the main character", prompt)
		self.assertIn("Tour the tower", prompt)

	def test_product_reference_preamble(self):
		with patch.object(
			film_director,
			"_asset_version_context",
			side_effect=lambda version, reference: {"media_type": "Image", "asset_category": "Product", "analysis": {}},
		):
			product_preamble = film_director.reference_preamble(["AV-MODEL"], [])
		self.assertEqual(
			"<Picture 1> is a reference subject: keep its shape, colours and details exactly.", product_preamble
		)

	def test_reference_to_video_renders_a_ten_second_take_in_one_pass(self):
		from joymedia.workflow_adapters.minimax_h3_profiles import MiniMaxH3ReferenceToVideoAdapter

		metadata = MiniMaxH3ReferenceToVideoAdapter.__new__(MiniMaxH3ReferenceToVideoAdapter).extract_execution_metadata({})
		self.assertGreaterEqual(metadata["frame_count"], film_director.MAX_TAKE_SECONDS * 24)
		self.assertLessEqual(metadata["frame_count"], 362)
		self.assertEqual(5, metadata["frame_count"] % 17)


class TestRoleInputCount(FrappeTestCase):
	def _workflow(self, *bindings):
		return frappe._dict(bindings=[frappe._dict(binding) for binding in bindings])

	def test_reference_slots_expect_one_input_per_slot(self):
		from joymedia.services.workflow_resolver import validate_role_input_count

		workflow = self._workflow(
			{"binding_key": "reference_image_1", "required_input_role": "product_reference", "required": 1, "value_type": "File Path"},
			{"binding_key": "reference_image_2", "required_input_role": "product_reference", "required": 1, "value_type": "File Path"},
		)

		validate_role_input_count(workflow, "product_reference", 2)
		with self.assertRaises(frappe.ValidationError):
			validate_role_input_count(workflow, "product_reference", 1)
		with self.assertRaises(frappe.ValidationError):
			validate_role_input_count(workflow, "product_reference", 3)

	def test_single_file_role_expects_exactly_one_input(self):
		from joymedia.services.workflow_resolver import validate_role_input_count

		workflow = self._workflow(
			{"binding_key": "first_frame", "required_input_role": "first_frame", "required": 1, "value_type": "File Path"},
		)

		validate_role_input_count(workflow, "first_frame", 1)
		with self.assertRaises(frappe.ValidationError):
			validate_role_input_count(workflow, "first_frame", 2)


class TestVisionAnalysis(FrappeTestCase):
	def test_analysis_is_normalized(self):
		analysis = vision_analysis.normalize_analysis(
			{"kind": "Person", "description": "A woman in a white ao dai", "outfit": "white ao dai", "extra": 1}
		)

		self.assertEqual("person", analysis["kind"])
		self.assertEqual("white ao dai", analysis["outfit"])
		self.assertNotIn("extra", analysis)
		self.assertEqual("other", vision_analysis.normalize_analysis({"kind": "spaceship"})["kind"])

	def test_describe_image_sends_image_to_vision_model(self):
		sent = {}

		def fake_post(url, json=None, timeout=None):
			sent["url"], sent["payload"] = url, json
			response = _response({"choices": [{"message": {"content": '{"kind": "place", "description": "Pool"}'}}]})
			response.raise_for_status = MagicMock()
			return response

		with (
			patch.dict(frappe.conf, {"qwen_vl_base_url": "http://vl/v1", "qwen_vl_model": "qwen-vl"}),
			patch.object(vision_analysis.requests, "post", side_effect=fake_post),
		):
			analysis = vision_analysis.describe_image("data:image/jpeg;base64,AAAA")

		self.assertEqual("http://vl/v1/chat/completions", sent["url"])
		content = sent["payload"]["messages"][0]["content"]
		self.assertEqual({"url": "data:image/jpeg;base64,AAAA"}, content[0]["image_url"])
		self.assertEqual("place", analysis["kind"])

	def test_unconfigured_vision_model_skips_analysis(self):
		with patch.dict(frappe.conf, {"qwen_vl_base_url": None, "qwen_vl_model": None}):
			self.assertEqual([], vision_analysis.ensure_project_image_analysis(frappe._dict(selected_media=[])))
