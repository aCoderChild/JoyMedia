import io
import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.review import consistency


class TestChecks(FrappeTestCase):
	def test_boolean_and_count_answers_cannot_impersonate_each_other(self):
		for expected, answer in (
			(True, {"answer": 1}),
			(False, {"answer": 0}),
			(1, {"count": True}),
			(consistency.AtMost(1), {"count": False}),
			(consistency.AtMost(1), {"count": -1}),
		):
			with (
				self.subTest(expected=expected, answer=answer),
				patch.object(consistency, "ask", return_value=answer),
			):
				self.assertEqual(
					consistency.run_checks([("p", "q", expected, "invalid evidence")]), ["invalid evidence"]
				)

	def test_multiple_approved_views_of_one_subject_count_as_one_cast_member(self):
		shot = frappe._dict(
			media_project="PROJECT",
			generation_inputs=[
				frappe._dict(reference_role="Character", asset_version="FRONT"),
				frappe._dict(reference_role="Character", asset_version="SIDE"),
				frappe._dict(reference_role="Product", asset_version="PACK"),
			],
		)
		with patch.object(
			frappe,
			"get_all",
			return_value=[frappe._dict(asset_version=v, identity_key="ACTOR") for v in ["FRONT", "SIDE"]],
		):
			self.assertEqual(consistency._cast_size(shot), 1)

	def test_a_failed_or_unclear_answer_fails_and_a_matching_one_passes(self):
		checks = [
			("p", consistency.COUNT, 2, "not two characters"),
			("p", consistency.shows("A bear spills juice"), True, "the action is not shown"),
		]
		answers = [{"count": "2"}, {"answer": False, "reason": "no juice"}]
		with patch.object(consistency, "ask", side_effect=answers):
			self.assertEqual(["the action is not shown (no juice)"], consistency.run_checks(checks))
		with patch.object(consistency, "ask", side_effect=[{"count": 2}, {}]):
			self.assertEqual(
				["the action is not shown"], consistency.run_checks(checks)
			)  # no answer is not a pass

	def test_a_take_frame_may_show_fewer_characters_but_never_more(self):
		check = [("p", consistency.COUNT, consistency.AtMost(2), "more characters")]
		for count, failures in ((0, []), (2, []), (3, ["more characters"]), ("x", ["more characters"])):
			with patch.object(consistency, "ask", return_value={"count": count}):
				self.assertEqual(failures, consistency.run_checks(check), count)

	def test_a_frame_is_checked_for_its_cast_and_described_action(self):
		shot = frappe._dict(
			keyframe_artifact="GART-1",
			media_project="PRJ-X",
			views_json="",
			generation_prompt="The kid spills juice. The kid panics. Camera: Close-up.\n\nAudio: a splash.",
			generation_inputs=[
				frappe._dict(reference_role="Character"),
				frappe._dict(reference_role="Product"),
			],
		)
		with patch.object(frappe.db, "get_value", return_value="/private/files/f.png"):
			checks = consistency.frame_checks(shot)
		self.assertEqual(
			[1, True, False, False], [expected for _p, _q, expected, _m in checks]
		)  # cast, action, no stranger, no character standing on the product
		self.assertIn('"The kid spills juice."', checks[1][1])
		self.assertNotIn("Camera", checks[1][1])
		self.assertIn("ON TOP OF the advertised product", checks[3][1])

	def test_a_split_screen_frame_is_checked_for_its_panels(self):
		shot = frappe._dict(
			keyframe_artifact="GART-1",
			media_project="PRJ-X",
			views_json=json.dumps([{"text": "A"}, {"text": "B"}, {"text": "C"}]),
			generation_prompt="Split screen.",
			generation_inputs=[],
		)
		with patch.object(frappe.db, "get_value", return_value="/private/files/f.png"):
			checks = consistency.frame_checks(shot)
		self.assertEqual(1, len(checks))
		self.assertIn("split screen of 3 separate panels", checks[0][1])

	def test_close_action_frame_rejects_visible_full_body_and_feet(self):
		shot = frappe._dict(
			keyframe_artifact="GART-1",
			media_project="PRJ-X",
			views_json="",
			generation_inputs=[frappe._dict(reference_role="Character")],
			motion_plan_json={
				"shot_structure": {
					"stage": "unfold",
					"framing": "extreme_close_up",
					"angle": "eye_level",
					"subject_motion": "manipulation",
					"keep_visible": [],
				},
			},
		)
		with patch.object(frappe.db, "get_value", return_value="/private/files/f.png"):
			checks = consistency.frame_checks(shot)
		self.assertTrue(any("Critical framing:" in meaning for *_rest, meaning in checks))

	def test_actor_without_product_reference_checks_for_extra_held_package(self):
		shot = frappe._dict(
			keyframe_artifact="GART-1",
			media_project="PRJ-X",
			views_json="",
			image_prompt="A mascot holding a loose cloth.",
			generation_inputs=[frappe._dict(reference_role="Character")],
		)
		with patch.object(frappe.db, "get_value", return_value="/private/files/f.png"):
			checks = consistency.frame_checks(shot)
		self.assertTrue(any("Critical prop:" in meaning for *_rest, meaning in checks))

	def test_product_scene_checks_authored_physical_support(self):
		shot = frappe._dict(
			keyframe_artifact="GART-1",
			media_project="PRJ-X",
			views_json="",
			start_state="The product pack rests on a side table.",
			generation_inputs=[frappe._dict(reference_role="Product")],
		)
		with patch.object(frappe.db, "get_value", return_value="/private/files/f.png"):
			checks = consistency.frame_checks(shot)
		self.assertTrue(any("Critical geometry: advertised product" in meaning for *_rest, meaning in checks))

	def test_still_review_uses_the_starting_frame_instead_of_future_actions(self):
		shot = frappe._dict(
			keyframe_artifact="GART-1",
			media_project="PRJ-X",
			views_json="",
			generation_inputs=[],
			image_prompt="A bear holding a cookie beside one intact glass.",
			generation_prompt="The bear reaches, knocks the glass over, then panics.",
		)
		with patch.object(frappe.db, "get_value", return_value="/private/files/f.png"):
			checks = consistency.frame_checks(shot)
		self.assertIn("A bear holding a cookie beside one intact glass", checks[0][1])
		self.assertNotIn("then panics", checks[0][1])
		self.assertIn("Future movements", checks[0][1])

	def test_the_sampled_frames_are_tiled_in_reading_order(self):
		from PIL import Image

		frames = []
		for colour in ("red", "green", "blue", "white"):
			buffer = io.BytesIO()
			Image.new("RGB", (10, 20), colour).save(buffer, "PNG")
			frames.append(buffer.getvalue())
		sheet = Image.open(io.BytesIO(consistency.contact_sheet(frames)))
		self.assertEqual((20, 40), sheet.size)
		self.assertEqual(
			[(255, 0, 0), (0, 128, 0), (0, 0, 255)], [sheet.getpixel(p) for p in ((5, 5), (15, 5), (5, 25))]
		)


class TestConsistencyLoop(FrappeTestCase):
	def test_late_review_cannot_write_over_replacement_evidence(self):
		shot = self._shot()
		shot._consistency_evidence = {"selected_output_asset_version": "OLD"}
		with (
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "sql", return_value=[{"selected_output_asset_version": "NEW"}]),
			patch.object(frappe.db, "set_value") as write,
			patch.object(consistency, "publish_project_event"),
		):
			self.assertFalse(consistency._record(shot, "Passed", ""))
		write.assert_not_called()

	def test_uncalibrated_physical_concern_requests_review_without_gpu_retry(self):
		recorded, redo = self._run(self._shot(), ["Physical staging review: missing contact"], kind="take")
		self.assertEqual(recorded, [("Needs Review", "Physical staging review: missing contact")])
		redo.assert_not_called()

	def test_clear_character_on_product_uses_bounded_frame_redraw(self):
		recorded, redo = self._run(
			self._shot(), ["Critical geometry: character stands on the advertised product"]
		)
		self.assertEqual("Redrawing", recorded[0][0])
		redo.assert_called_once_with("PRJ-X")
		recorded, redo = self._run(
			self._shot(consistency.MAX_FRAME_REDOS),
			["Critical geometry: character stands on the advertised product"],
		)
		self.assertEqual("Needs Review", recorded[0][0])
		redo.assert_not_called()

	def test_full_body_in_close_detail_uses_bounded_frame_redraw(self):
		recorded, redo = self._run(
			self._shot(), ["Critical framing: full character body appears in a close product/action detail"]
		)
		self.assertEqual("Redrawing", recorded[0][0])
		redo.assert_called_once_with("PRJ-X")

	def test_no_checks_is_not_a_pass(self):
		with (
			patch.object(frappe, "set_user"),
			patch.object(frappe, "get_doc", return_value=self._shot()),
			patch.object(consistency, "frame_checks", return_value=[]),
			patch.object(consistency, "_record") as record,
		):
			consistency.check_scene("SHOT-X", "frame", "test@example.com")
		self.assertEqual(record.call_args.args[1], "Not Checked")

	def _shot(self, retries=0):
		return frappe._dict(name="SHOT-X", media_project="PRJ-X", consistency_retries=retries)

	def _run(self, shot, failures, kind="frame"):
		recorded = []
		with (
			patch.object(frappe, "set_user"),
			patch.object(frappe, "get_doc", return_value=shot),
			patch.object(consistency, "frame_checks", return_value=["c"]),
			patch.object(consistency, "take_checks", return_value=["c"]),
			patch.object(
				consistency,
				"run_checks",
				side_effect=failures if isinstance(failures, Exception) else None,
				return_value=failures,
			),
			patch.object(
				consistency, "_record", side_effect=lambda s, status, notes: recorded.append((status, notes))
			),
			patch.object(frappe.db, "set_value"),
			patch.object(consistency, "redo_waiting") as redo,
		):
			consistency.check_scene(shot.name, kind, "user@example.com")
		return recorded, redo

	def test_a_consistent_frame_passes(self):
		recorded, redo = self._run(self._shot(), [])
		self.assertEqual([("Passed", "")], recorded)
		redo.assert_not_called()

	def test_an_action_judge_cannot_discard_authored_source_art_restoration(self):
		shot = self._shot()
		shot.selected_output_asset_version = "REPAIRED-TAKE"
		with patch.object(frappe.db, "get_value", return_value='{"planes":[{}]}'):
			recorded, redo = self._run(shot, ["possible action concern"], kind="take")
		self.assertEqual([("Needs Review", "possible action concern")], recorded)
		redo.assert_not_called()

	def test_an_inconsistent_frame_waits_for_a_redraw_until_the_limit_then_is_left_for_review(self):
		recorded, redo = self._run(self._shot(0), ["no juice"])
		self.assertEqual([("Redrawing", "no juice")], recorded)
		redo.assert_called_once_with("PRJ-X")
		recorded, redo = self._run(self._shot(consistency.MAX_FRAME_REDOS), ["no juice"])
		self.assertEqual([("Needs Review", "no juice")], recorded)
		redo.assert_not_called()

	def test_an_inconsistent_take_waits_for_one_redo(self):
		recorded, _redo = self._run(self._shot(0), ["an extra bear appears"], kind="take")
		self.assertEqual("Redoing", recorded[-1][0])
		recorded, _redo = self._run(
			self._shot(consistency.MAX_TAKE_REDOS), ["an extra bear appears"], kind="take"
		)
		self.assertEqual("Needs Review", recorded[-1][0])

	def test_a_delayed_judge_cannot_redraw_a_human_approved_frame(self):
		shot = self._shot()
		shot.keyframe_status = "Approved"
		recorded, redo = self._run(shot, ["possible issue"])
		self.assertEqual([("Needs Review", "possible issue")], recorded)
		redo.assert_not_called()

	def test_an_unreachable_judge_leaves_the_scene_unchecked(self):
		recorded, redo = self._run(self._shot(), ConnectionError("port 8002 timed out"))
		self.assertEqual("Not Checked", recorded[-1][0])
		redo.assert_not_called()

	def test_waiting_scenes_go_in_one_run_and_only_when_no_run_is_going(self):
		names = {"Redrawing": ["S1", "S3"], "Redoing": []}
		with (
			patch.object(frappe.db, "sql", return_value=[[1]]),
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(
				frappe,
				"get_all",
				side_effect=lambda doctype, filters, **kw: names[filters["consistency_status"]],
			),
			patch("joymedia.services.keyframes.stage.generate_keyframes") as redraw,
		):
			consistency.redo_waiting("PRJ-X")
		redraw.assert_called_once_with("PRJ-X", ["S1", "S3"], automatic=True)
		with (
			patch.object(frappe.db, "sql", return_value=[[1]]),
			patch.object(frappe.db, "exists", return_value=True),
			patch("joymedia.services.keyframes.stage.generate_keyframes") as redraw,
		):
			consistency.redo_waiting("PRJ-X")
		redraw.assert_not_called()


class TestAsk(FrappeTestCase):
	def test_one_picture_and_one_question_go_to_the_configured_model(self):
		from PIL import Image

		buffer = io.BytesIO()
		Image.new("RGB", (1600, 900), "white").save(buffer, "PNG")
		reply = MagicMock()
		reply.json.return_value = {"choices": [{"message": {"content": json.dumps({"count": 2})}}]}
		with (
			patch.dict(
				frappe.conf,
				{
					"joymedia_vision": None,
					"qwen_vl_base_url": "http://vl:8002/v1/",
					"qwen_vl_model": "vl-model",
				},
			),
			patch.object(consistency.requests, "post", return_value=reply) as post,
		):
			self.assertEqual({"count": 2}, consistency.ask(buffer.getvalue(), consistency.COUNT))
		payload = post.call_args.kwargs["json"]
		self.assertEqual("http://vl:8002/v1/chat/completions", post.call_args.args[0])
		self.assertEqual(["image_url", "text"], [part["type"] for part in payload["messages"][0]["content"]])


class TestLocate(FrappeTestCase):
	def test_a_box_is_read_in_the_sent_pictures_pixels_and_scaled_back_and_an_implausible_one_is_dropped(
		self,
	):
		from PIL import Image

		buffer = io.BytesIO()
		Image.new("RGB", (720, 1280), "white").save(buffer, "PNG")

		def reply(box):
			response = MagicMock()
			response.json.return_value = {
				"choices": [
					{"message": {"content": f'```json\n[{{"bbox_2d": {box}, "label": "pack"}}]\n```'}}
				]
			}
			return response

		conf = {"qwen_vl_base_url": "http://vl:8002/v1", "qwen_vl_model": "vl"}
		with (
			patch.dict(frappe.conf, conf),
			patch.object(consistency.requests, "post", return_value=reply([85, 349, 167, 424])),
		):
			self.assertEqual((243, 997, 477, 1211), consistency.locate(buffer.getvalue(), "the pack"))
		with (
			patch.dict(frappe.conf, conf),
			patch.object(consistency.requests, "post", return_value=reply([0, 0, 252, 448])),
		):
			self.assertIsNone(
				consistency.locate(buffer.getvalue(), "the pack")
			)  # the whole picture is not a pack


class TestOutsiders(FrappeTestCase):
	def test_a_scene_of_illustrated_characters_is_checked_for_a_strangers_arm_and_one_with_a_real_person_is_not(
		self,
	):
		mascot = frappe._dict(
			keyframe_artifact="GART-1",
			media_project="PRJ-X",
			views_json="",
			generation_prompt="The mascot wipes the table.",
			generation_inputs=[frappe._dict(reference_role="Character")],
		)
		person = frappe._dict(mascot, generation_inputs=[frappe._dict(reference_role="Person")])
		with patch.object(frappe.db, "get_value", return_value="/private/files/f.png"):
			self.assertIn(
				consistency.OUTSIDER, [question for _p, question, _e, _m in consistency.frame_checks(mascot)]
			)
			self.assertNotIn(
				consistency.OUTSIDER, [question for _p, question, _e, _m in consistency.frame_checks(person)]
			)


class TestExplicitTakeCheck(FrappeTestCase):
	def test_recheck_rejects_changed_or_foreign_take_without_queuing(self):
		project = MagicMock(name="PROJECT")
		for shot in [
			frappe._dict(media_project="OTHER", selected_output_asset_version="TAKE"),
			frappe._dict(media_project="PROJECT", selected_output_asset_version="NEW"),
		]:
			with (
				patch.object(frappe, "get_doc", side_effect=[project, shot]),
				patch.object(frappe.db, "sql"),
				patch.object(consistency, "queue_check") as queue,
				self.assertRaises(
					frappe.ValidationError if shot.media_project == "PROJECT" else frappe.PermissionError
				),
			):
				project.name = "PROJECT"
				consistency.request_scene_check("PROJECT", "SHOT", "TAKE")
			queue.assert_not_called()

	def test_explicit_check_uses_owner_access_and_exact_selected_take(self):
		project = MagicMock()
		project.name = "PROJECT"
		shot = frappe._dict(name="SHOT", media_project="PROJECT", selected_output_asset_version="TAKE")
		with (
			patch.object(frappe, "get_doc", side_effect=[project, shot]),
			patch.object(frappe.db, "sql"),
			patch.object(consistency, "is_configured", return_value=True),
			patch.object(consistency, "queue_check") as queue,
		):
			self.assertEqual(
				consistency.request_scene_check("PROJECT", "SHOT", "TAKE"),
				{"status": "Checking", "take": "TAKE"},
			)
		project._require_write_access.assert_called_once()
		queue.assert_called_once_with("SHOT", "take")


class TestTemporalEvidenceRead(FrappeTestCase):
	def test_foreign_or_replaced_take_cannot_read_findings(self):
		for parent, take in [("OTHER", "TAKE"), ("PROJECT", "NEW")]:
			project = MagicMock()
			project.name = "PROJECT"
			shot = frappe._dict(media_project=parent, selected_output_asset_version=take)
			with (
				patch.object(frappe, "get_doc", side_effect=[project, shot]),
				patch.object(frappe, "get_all") as files,
				self.assertRaises(frappe.PermissionError if parent == "OTHER" else frappe.ValidationError),
			):
				consistency.get_scene_check_evidence("PROJECT", "SHOT", "TAKE")
			files.assert_not_called()

	def test_read_requires_project_read_access_before_any_evidence_lookup(self):
		project = MagicMock()
		project._require_read_access.side_effect = frappe.PermissionError
		with (
			patch.object(frappe, "get_doc", return_value=project),
			patch.object(frappe, "get_all") as files,
			self.assertRaises(frappe.PermissionError),
		):
			consistency.get_scene_check_evidence("PROJECT", "SHOT", "TAKE")
		files.assert_not_called()

	def test_missing_evidence_is_not_a_pass(self):
		project = MagicMock()
		project.name = "PROJECT"
		shot = frappe._dict(
			media_project="PROJECT",
			selected_output_asset_version="TAKE",
			generation_prompt="Action",
			motion_plan_json="{}",
		)
		with (
			patch.object(frappe, "get_doc", side_effect=[project, shot]),
			patch.object(frappe, "get_all", return_value=[]),
			patch.object(frappe.db, "get_value", return_value="HASH"),
		):
			self.assertIsNone(consistency.get_scene_check_evidence("PROJECT", "SHOT", "TAKE"))
