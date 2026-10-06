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

# Roles left "General" (automatic): the category, then the image analysis decide.
REFERENCES = [
	{"reference_key": "model", "media_type": "Image", "asset_category": "Character", "reference_role": "General", "asset_name": "model"},
	{"reference_key": "tower", "media_type": "Image", "asset_category": "Reference", "reference_role": "General", "asset_name": "tower",
	 "analysis": {"kind": "place", "description": "Cream high-rise tower at golden hour"}},
	{"reference_key": "bedroom", "media_type": "Image", "asset_category": "Background", "reference_role": "General", "asset_name": "bedroom"},
	{"reference_key": "logo", "media_type": "Image", "asset_category": "Brand", "reference_role": "General", "asset_name": "logo"},
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

	def test_what_people_chose_beats_the_image_analysis(self):
		# A product that is a painting of a harbour: the analysis sees a place.
		painting = {"media_type": "Image", "reference_role": "Product", "asset_category": "Reference",
			"analysis": {"kind": "place"}}
		self.assertEqual(film_director.PRODUCT, film_director.classify_reference(painting))
		# Role left automatic: the category decides, then the analysis.
		self.assertEqual(film_director.PRODUCT, film_director.classify_reference(
			{**painting, "reference_role": "General", "asset_category": "Product"}))
		self.assertEqual(film_director.PLACE, film_director.classify_reference(
			{**painting, "reference_role": "General"}))
		self.assertEqual(film_director.CHARACTER, film_director.classify_reference(
			{"media_type": "Image", "reference_role": "General", "analysis": {"kind": "person"}}))

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

		self.assertEqual(["tower", "tower"], [ref["reference_key"] for ref in shots[0]["references"]])

	def test_tags_beyond_the_sent_images_point_at_the_place(self):
		# Planners confuse place keys named "3"/"4" with picture numbers.
		shots = [{"generation_prompt": "The person from <Picture 1> walks through the place from <Picture 4>.",
		          "references": [{"reference_key": "model"}, {"reference_key": "bedroom"}]}]

		film_director.normalize_story_references(shots, REFERENCES, "product_reference")

		self.assertTrue(shots[0]["generation_prompt"].startswith(
			"The person from <Picture 1> walks through the place from <Picture 2>. One continuous shot with no cuts"
		))

	def test_plan_problems_catch_short_repeated_and_overused_plans(self):
		take = lambda prompt, place: {"generation_prompt": prompt, "references": [{"reference_key": "model"}, {"reference_key": place}]}

		self.assertEqual([], film_director.plan_problems([take("a", "p1"), take("b", "p2"), take("c", "p1")], 3))
		problems = film_director.plan_problems([take("same", "p1"), take("same", "p1"), take("x", "p1")], 4)
		self.assertEqual(3, len(problems))

	def test_roster_flags_images_without_a_description(self):
		references = [
			{"reference_key": "3", "media_type": "Image", "asset_category": "Background", "asset_name": "3"},
			{"reference_key": "lobby", "media_type": "Image", "asset_category": "Background", "asset_name": "lobby"},
		]

		self.assertEqual("- key=3: (no visual description available)", film_director._roster_line(references[0]))
		self.assertEqual("- key=lobby: lobby", film_director._roster_line(references[1]))

	def test_director_instruction_lists_roster_and_role(self):
		instruction = film_director.build_director_instruction(REFERENCES, "product_reference", 25)

		self.assertIn('usage_role "product_reference"', instruction)
		self.assertIn("key=model", instruction)
		self.assertIn("key=tower: Cream high-rise tower at golden hour", instruction)
		self.assertNotIn("key=logo", instruction)
		self.assertIn("<Picture 1>", instruction)
		self.assertIn("Plan exactly 3 long continuous takes", instruction)
		fixed_text = (film_director.DIRECTOR_RULES + film_director.FEW_SHOT_EXAMPLE).lower()
		for genre_specific in ("real-estate", "property", "golden hour", "teal", "ao dai", "luxury"):
			self.assertNotIn(genre_specific, fixed_text)

	def test_take_count_keeps_every_take_within_model_range(self):
		self.assertEqual((2, 3), film_director.take_count_range(15))
		self.assertEqual((3, 5), film_director.take_count_range(25))
		self.assertEqual((6, 6), film_director.take_count_range(60))
		self.assertEqual((2, 2), film_director.take_count_range(5))

	def test_story_plans_one_take_per_place_within_the_renderable_range(self):
		places = [{"reference_key": f"p{n}", "media_type": "Image", "asset_category": "Background"} for n in range(6)]

		# Six places in 30 s: every take must still be >= 124 frames, so five fit.
		self.assertEqual(5, film_director.story_take_count(30, places))
		self.assertEqual(3, film_director.story_take_count(30, places[:2]))
		self.assertEqual(2, film_director.story_take_count(15, places))
		self.assertEqual(6, film_director.story_take_count(60, places))

	def test_every_film_has_an_opening_a_peak_and_an_ending(self):
		self.assertEqual(["OPENING", "CLOSING"], film_director.story_beats(2))
		self.assertEqual(["OPENING", "CLIMAX", "CLOSING"], film_director.story_beats(3))
		self.assertEqual(["OPENING", "BUILD", "CLIMAX", "RESOLUTION", "CLOSING"], film_director.story_beats(5))
		self.assertEqual(["OPENING", "BUILD", "BUILD", "CLIMAX", "RESOLUTION", "CLOSING"], film_director.story_beats(6))

		instruction = film_director.build_director_instruction(REFERENCES, "product_reference", 25)
		self.assertIn("- Take 1 OPENING:", instruction)
		self.assertIn("- Take 2 CLIMAX:", instruction)
		self.assertIn("- Take 3 CLOSING:", instruction)

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

		self.assertEqual(["tower", "tower"], [ref["reference_key"] for ref in shots[0]["references"]])

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
			# Keep the planning request; the later on-screen-words request has no plan to return.
			if "on-screen words" in json["messages"][1]["content"]:
				return _response({"choices": [{"message": {"content": "{}"}}]})
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
		self.assertIn("Return exactly 2 takes as shots.", prompt)
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

	def test_continuation_prompt_keeps_the_reference_pictures(self):
		# Continuations receive the take's reference images, so their tags stay.
		prompt = self._compile(self._snapshot(), segment_index=2, segment_count=2)

		self.assertTrue(prompt.startswith("<Picture 1> is the main character"))
		self.assertIn("The person from <Picture 1> rests in the place from <Picture 2>.", prompt)
		self.assertIn("continuation segment 2 of 2", prompt)

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
			"<Picture 1> is the product: keep its exact shape, size, colours, patterns and details. "
			"It is an object in the scene, never the setting.",
			product_preamble,
		)

	def test_reference_to_video_takes_render_in_short_segments(self):
		from joymedia.services.generation_segment_planner import plan_generation_segments
		from joymedia.workflow_adapters.minimax_h3_profiles import MiniMaxH3ReferenceToVideoAdapter

		adapter = MiniMaxH3ReferenceToVideoAdapter.__new__(MiniMaxH3ReferenceToVideoAdapter)
		frame_count = adapter.extract_execution_metadata({})["frame_count"]
		self.assertEqual(5, frame_count % 17)
		segments = plan_generation_segments(
			film_director.MAX_TAKE_SECONDS * 24, frame_count, adapter.continuation_overlap_frames
		)
		# Every render is ~5 s at most; the take is continued, not rendered in one long pass.
		self.assertGreater(len(segments), 1)
		self.assertTrue(all(segment["segment_frame_count"] <= 5.2 * 24 for segment in segments))


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


class TestContinuationReferences(FrappeTestCase):
	def test_continuation_receives_the_take_reference_images_as_pictures(self):
		import json
		from pathlib import Path

		from joymedia.workflow_adapters.minimax_h3_sato import MiniMaxH3SatoContinuationAdapter

		workflow = json.loads(
			(Path(__file__).parents[1] / "workflows" / "minimax_h3" / "minimax_h3_sato_continuation.json").read_text()
		)
		MiniMaxH3SatoContinuationAdapter().finalize_workflow(
			workflow, None,
			{"product_reference": ["person.png", "lobby.png"], "seed_video": "take.mp4", "seed_video_size": (1344, 768)},
		)

		context = workflow["328"]["inputs"]
		self.assertEqual(["joymedia_reference_1", 0], context["media_1"])
		self.assertEqual("image", context["media_type_2"])
		self.assertEqual("lobby.png", workflow["joymedia_reference_2"]["inputs"]["image"])
		# The saved latent cannot be resized, so the continuation matches the take's size.
		self.assertEqual(("custom", 1344, 768), (context["resolution"], context["width"], context["height"]))


class TestFilmEnding(FrappeTestCase):
	def test_last_shot_is_directed_to_end_the_film_once(self):
		shots = [{"generation_prompt": "Opening."}, {"generation_prompt": "Final view of the garden."}]

		film_director.close_the_film(shots)
		film_director.close_the_film(shots)

		self.assertEqual("Opening.", shots[0]["generation_prompt"])
		self.assertEqual(1, shots[1]["generation_prompt"].count(film_director.CLOSING_DIRECTION))


class TestProjectNaming(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _project(self, name):
		return frappe.get_doc({"doctype": "Media Project", "project_name": name, "product_name": ""}).insert(
			ignore_permissions=True
		)

	def test_untitled_project_takes_the_storyboard_title(self):
		from joymedia.services.video_plan_service import _name_untitled_project

		untitled, named = self._project("Dự án mới"), self._project("Spring launch")
		for project in (untitled, named):
			_name_untitled_project(project, "Sắc xuân bên hồ")

		self.assertEqual("Sắc xuân bên hồ", frappe.db.get_value("Media Project", untitled.name, "project_name"))
		self.assertEqual("Spring launch", frappe.db.get_value("Media Project", named.name, "project_name"))

	def test_project_without_product_name_can_be_deleted(self):
		from joymedia.joymedia.doctype.media_project.media_project import archive_project

		project = self._project("Dự án mới")

		self.assertTrue(archive_project(project.name)["archived"])
		self.assertEqual("Archived", frappe.db.get_value("Media Project", project.name, "status"))


class TestTranslation(FrappeTestCase):
	@patch("joymedia.services.qwen_client.requests.post")
	def test_english_music_text_is_not_sent_for_translation(self, post):
		from joymedia.services.qwen_client import to_english

		self.assertEqual("soft piano", to_english("soft piano"))
		post.assert_not_called()


class TestTakeLengthsFitRenderJobs(FrappeTestCase):
	def test_takes_just_over_one_job_give_their_spare_time_to_the_climax(self):
		names = ["OPENING", "BUILD", "CLIMAX", "RESOLUTION", "CLOSING"]
		shots = film_director.balance_take_durations(
			[{"duration_seconds": 6, "shot_name": f"{name}: take"} for name in names], 30
		)

		lengths = [round(shot["duration_seconds"], 2) for shot in shots]
		self.assertAlmostEqual(30, sum(shot["duration_seconds"] for shot in shots))
		self.assertEqual(round(film_director.MIN_RENDER_SECONDS, 2), lengths[0])
		self.assertEqual(max(lengths), lengths[2])


class TestDirectorGuards(FrappeTestCase):
	def test_take_drifting_out_of_its_place_is_reported(self):
		shots = [{"generation_prompt": "She steps onto the balcony at sunset.", "references": [{"reference_key": "lobby"}]}]
		places = {"lobby": "lobby a modern interior with a reception desk and wooden paneling"}

		problems = film_director.plan_problems(shots, 1, places)

		self.assertEqual(1, len(problems))
		self.assertIn("balcony", problems[0])
		self.assertEqual([], film_director.invented_places("She waits by the reception desk.", places["lobby"]))

	def test_beat_words_follow_the_story_arc_whatever_the_planner_wrote(self):
		shots = [{"shot_name": "Biến thể 1: Dạo bước"}, {"shot_name": "Khoảnh khắc cuối"}]

		film_director.name_story_beats(shots)

		self.assertEqual(["OPENING: Dạo bước", "CLOSING: Khoảnh khắc cuối"], [shot["shot_name"] for shot in shots])

	def test_character_roster_gives_the_look_not_the_photo_background(self):
		context = {
			"reference_key": "nu_ao_dai",
			"analysis": {"description": "A woman stands outdoors among lotus flowers.", "outfit": "white ao dai, long hair"},
		}

		line = film_director._roster_line(context, person=True)

		self.assertIn("white ao dai", line)
		self.assertNotIn("lotus", line)


class TestPlannerCutOff(FrappeTestCase):
	@patch("joymedia.services.qwen_client._completion_budget", return_value=1000)
	@patch("joymedia.services.qwen_client._qwen_config", return_value=("http://qwen/v1", "m", 60))
	@patch("joymedia.services.qwen_client.requests.post")
	def test_cut_off_plan_is_requested_again_without_replaying_it(self, post, config, budget):
		cut_off = MagicMock(ok=True)
		cut_off.json.return_value = {"choices": [{"message": {"content": '{"shots": [{"generation_prompt": "A lo'}}]}
		good = MagicMock(ok=True)
		good.json.return_value = {"choices": [{"message": {"content": (
			'{"film_title": "Buổi sáng", "shots": [{"shot_number": 1, "shot_name": "Mở", "duration_seconds": 5,'
			' "generation_prompt": "A slow push-in on the product.", "references": []}]}'
		)}}]}
		post.side_effect = [cut_off, good]

		with patch("joymedia.services.qwen_client._validate_video_plan"):
			plan = qwen_client.generate_video_plan(
				product_name="P", video_idea="I", total_video_duration=5, target_fps=24, shot_count=1
			)

		self.assertEqual("Buổi sáng", plan["film_title"])
		retry_messages = post.call_args_list[1].kwargs["json"]["messages"]
		self.assertEqual(2, len(retry_messages))
		self.assertIn("cut off", retry_messages[1]["content"])


class TestPlannerOutputCleanup(FrappeTestCase):
	def test_leaked_example_numbering_is_removed_from_titles(self):
		self.assertEqual("Áo dài trắng dạo quanh căn hộ", qwen_client.clean_title("Biến thể TVC 179: Áo dài trắng dạo quanh căn hộ"))
		self.assertEqual("Sống xanh 2024", qwen_client.clean_title("Sống xanh 2024"))
		self.assertEqual("", qwen_client.clean_title("Biến thể TVC 297"))
		self.assertEqual("Đẹp", qwen_client.clean_title("Biến thể Đẹp"))
		self.assertEqual("Biển xanh", qwen_client.clean_title("Biển xanh"))

	def test_empty_captions_fall_back_to_the_scene_title_except_the_last(self):
		shots = [{"shot_name": "OPENING: Bước đi tự tin", "caption": ""}, {"shot_name": "CLOSING: Hoàng hôn", "caption": ""}]

		qwen_client.default_captions(shots)

		self.assertEqual(["Bước đi tự tin", ""], [shot["caption"] for shot in shots])

	@patch("joymedia.services.qwen_client.requests.post")
	def test_english_ideas_go_to_the_planner_unchanged(self, post):
		self.assertEqual("A sunset tour of the tower.", qwen_client._idea_for_planner("A sunset tour of the tower."))
		post.assert_not_called()


PRODUCT_FILM = [
	{"reference_key": "nu_ao_dai", "media_type": "Image", "reference_role": "Character", "asset_name": "nữ áo dài",
	 "analysis": {"kind": "person", "outfit": "white ao dai"}},
	{"reference_key": "tranh", "media_type": "Image", "reference_role": "Product", "asset_name": "1",
	 "analysis": {"kind": "place", "description": "A coastal town at sunset with boats and a lighthouse."}},
]


class TestProductFilm(FrappeTestCase):
	def test_character_with_a_product_is_a_product_film_not_a_walk_through_it(self):
		self.assertTrue(film_director.is_product_film(PRODUCT_FILM))

		instruction = film_director.build_director_instruction(PRODUCT_FILM, "product_reference", 25)

		self.assertIn("is an OBJECT", instruction)
		self.assertIn("key=tranh: THE PRODUCT, an object (not a place)", instruction)
		self.assertNotIn("follows the character through the supplied places", instruction)

	def test_takes_reference_the_character_and_product_and_hero_takes_the_product_twice(self):
		shots = [
			{"generation_prompt": "She lifts the artwork toward the window light.", "references": []},
			{"generation_prompt": "A slow orbit around the artwork on a marble table.", "references": []},
		]

		film_director.normalize_story_references(shots, PRODUCT_FILM, "product_reference")

		self.assertEqual(
			[["nu_ao_dai", "tranh"], ["tranh", "tranh"]],
			[[ref["reference_key"] for ref in shot["references"]] for shot in shots],
		)


class TestGroundedWords(FrappeTestCase):
	@patch("joymedia.services.qwen_client._qwen_config", return_value=("http://qwen/v1", "m", 60))
	@patch("joymedia.services.qwen_client.requests.post")
	def test_titles_and_captions_come_from_what_the_scenes_show(self, post, config):
		post.return_value = _response({"choices": [{"message": {"content": frappe.as_json({
			"film_title": "Ánh hoàng hôn",
			"scenes": [{"title": "Nâng niu tác phẩm", "caption": "Tinh tế từng chi tiết"},
				{"title": "Cận cảnh viền đá", "caption": "Kết thúc"}],
		})}}]})
		shots = [
			{"shot_name": "OPENING: Siêu xe tăng tốc", "generation_prompt": "She lifts the artwork."},
			{"shot_name": "CLOSING: Nhẫn kim cương", "generation_prompt": "A close-up of the artwork's border."},
		]

		words = qwen_client.write_titles_and_captions(shots, "Quảng cáo sản phẩm")
		qwen_client.default_captions(shots)

		self.assertEqual("Ánh hoàng hôn", words["film_title"])
		self.assertEqual(["OPENING: Nâng niu tác phẩm", "CLOSING: Cận cảnh viền đá"], [s["shot_name"] for s in shots])
		self.assertEqual(["Tinh tế từng chi tiết", ""], [s["caption"] for s in shots])


class TestProductAnalysis(FrappeTestCase):
	@patch("joymedia.services.vision_analysis.analyse_asset_version")
	@patch("joymedia.services.vision_analysis.is_configured", return_value=True)
	def test_product_references_are_described_as_objects(self, configured, analyse):
		project = frappe._dict(selected_media=[frappe._dict(asset_version="AV-1", reference_role="Product")])
		version = frappe._dict(name="AV-1", media_asset="MA-1", file="/f.png", analysis_status="Ready",
			analysis_json='{"kind": "place", "version": 2}')
		with patch.object(vision_analysis.frappe.db, "get_value", side_effect=[version, "Image"]):
			vision_analysis.ensure_project_image_analysis(project)

		analyse.assert_called_once_with("AV-1", as_product=True)
