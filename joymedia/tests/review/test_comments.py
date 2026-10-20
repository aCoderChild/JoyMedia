import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.review import comments as review
from joymedia.tests.editing.test_timeline import _create_output_version, _create_workflow


def _scene(project, number, prompt="Original."):
	shot = frappe.get_doc(
		{
			"doctype": "Shot",
			"media_project": project.name,
			"shot_number": number,
			"shot_name": f"Scene {number}",
			"generation_prompt": prompt,
			"image_prompt": prompt,
			"duration_seconds": 2,
		}
	).insert(ignore_permissions=True)
	asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": f"{shot.name} Output",
			"media_type": "Video",
			"asset_category": "Other",
			"asset_scope": "Project Output",
			"media_project": project.name,
		}
	).insert(ignore_permissions=True)
	output = _create_output_version(project, f"out-{number}.mp4", 1, asset)[1]
	shot.db_set("selected_output_asset_version", output.name, update_modified=False)
	return shot, output


class ReviewCommentCase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		frappe.set_user("Administrator")
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Comments",
				"workflow": _create_workflow(),
				"total_duration_seconds": 4,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)
		self.one, self.one_take = _scene(self.project, 1)
		self.two, self.two_take = _scene(self.project, 2)
		self.limit, self.fps = review._frame_limit(self.project, self.one)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def add(self, shot=None, text="Make it brighter.", start=0, end=None):
		return review.add_review_comment(self.project.name, (shot or self.one).name, text, start, end)


class TestAddingComments(ReviewCommentCase):
	def test_a_single_frame_comment_is_anchored_to_the_take(self):
		row = self.add(start=12)
		self.assertEqual((12, 12), (row["start_frame"], row["end_frame"]))
		self.assertEqual(self.one_take.name, row["output_asset_version"])
		self.assertEqual("Open", row["status"])
		self.assertTrue(row["current_take"])

	def test_a_range_keeps_both_ends_and_a_reversed_range_is_put_in_order(self):
		self.assertEqual((5, 20), tuple(self.add(start=5, end=20)[k] for k in ("start_frame", "end_frame")))
		self.assertEqual((5, 20), tuple(self.add(start=20, end=5)[k] for k in ("start_frame", "end_frame")))

	def test_a_range_running_past_the_end_is_cut_to_the_last_frame_and_a_start_past_it_is_refused(self):
		self.assertEqual(self.limit - 1, self.add(start=1, end=self.limit + 500)["end_frame"])
		with self.assertRaises(frappe.ValidationError):
			self.add(start=self.limit)

	def test_bad_frame_values_are_refused(self):
		for bad in (-1, "abc", 1.5, float("nan"), float("inf"), None, [], {}):
			with self.subTest(bad=bad), self.assertRaises(frappe.ValidationError):
				self.add(start=bad)

	def test_numeric_strings_from_the_browser_are_accepted(self):
		self.assertEqual(7, self.add(start="7", end="9")["start_frame"])

	def test_empty_whitespace_and_oversized_comments_are_refused(self):
		for bad in ("", "   \n\t ", None, "x" * 2001):
			with self.subTest(bad=bad), self.assertRaises(frappe.ValidationError):
				self.add(text=bad)

	def test_markup_is_stripped_and_whitespace_is_tidied(self):
		row = self.add(text="  <b onclick='x()'>Tighten</b>\n\n  <script>alert(1)</script>   the shot ")
		self.assertNotIn("<", row["comment"])
		self.assertEqual(row["comment"], " ".join(row["comment"].split()))
		self.assertTrue(row["comment"].startswith("Tighten") and row["comment"].endswith("the shot"))

	def test_a_scene_without_a_take_cannot_be_commented(self):
		bare = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 3,
				"duration_seconds": 2,
				"generation_prompt": "x",
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self.add(shot=bare)

	def test_a_scene_of_another_project_is_refused(self):
		other = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Other",
				"workflow": self.project.workflow,
				"total_duration_seconds": 4,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)
		foreign, _take = _scene(other, 1)
		with self.assertRaises(frappe.ValidationError):
			self.add(shot=foreign)

	def test_one_scene_holds_at_most_fifty_open_comments(self):
		for number in range(review.MAX_OPEN_PER_SCENE):
			self.add(start=number % self.limit)
		with self.assertRaises(frappe.ValidationError):
			self.add()
		self.add(shot=self.two)  # another scene is unaffected


class TestListingAndStatus(ReviewCommentCase):
	def test_comments_come_back_in_scene_then_frame_order_with_seconds(self):
		self.add(shot=self.two, start=3)
		self.add(start=20, text="late")
		self.add(start=2, end=10, text="early")
		rows = review.get_review_comments(self.project.name)
		self.assertEqual(["early", "late", "Make it brighter."], [r["comment"] for r in rows])
		self.assertEqual(
			(round(2 / self.fps, 3), round(11 / self.fps, 3)),
			(rows[0]["start_seconds"], rows[0]["end_seconds"]),
		)
		self.assertEqual(1, len(review.get_review_comments(self.project.name, self.two.name)))

	def test_a_comment_on_an_older_take_is_marked_not_current(self):
		row = self.add()
		new_take = _create_output_version(
			self.project,
			"second.mp4",
			2,
			frappe.get_doc("Media Asset", {"asset_name": f"{self.one.name} Output"}),
		)[1]
		self.one.db_set("selected_output_asset_version", new_take.name, update_modified=False)
		listed = review.get_review_comments(self.project.name, self.one.name)
		self.assertEqual([(row["name"], False)], [(r["name"], r["current_take"]) for r in listed])

	def test_resolve_reopen_and_delete(self):
		row = self.add()
		review.set_review_comment_status(self.project.name, row["name"], "Resolved")
		doc = frappe.get_doc("Review Comment", row["name"])
		self.assertEqual(("Resolved", "Administrator"), (doc.status, doc.resolved_by))
		review.set_review_comment_status(self.project.name, row["name"], "Open")
		self.assertIsNone(frappe.get_doc("Review Comment", row["name"]).resolved_by)
		with self.assertRaises(frappe.ValidationError):
			review.set_review_comment_status(self.project.name, row["name"], "Addressed")
		review.delete_review_comment(self.project.name, row["name"])
		self.assertFalse(frappe.db.exists("Review Comment", row["name"]))

	def test_a_comment_of_another_project_cannot_be_changed(self):
		other = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Other",
				"workflow": self.project.workflow,
				"total_duration_seconds": 4,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)
		row = self.add()
		for call in (
			lambda: review.set_review_comment_status(other.name, row["name"], "Resolved"),
			lambda: review.delete_review_comment(other.name, row["name"]),
		):
			with self.assertRaises(frappe.ValidationError):
				call()


class TestPermissions(ReviewCommentCase):
	def _user(self, email):
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Stranger",
					"send_welcome_email": 0,
					"roles": [{"role": "JoyMedia User"}],
				}
			).insert(ignore_permissions=True)
		return email

	def test_someone_who_does_not_own_the_project_can_neither_read_nor_write_comments(self):
		row = self.add()
		frappe.set_user(self._user("stranger-review@example.com"))
		for call in (
			lambda: review.get_review_comments(self.project.name),
			lambda: review.add_review_comment(self.project.name, self.one.name, "hi", 1),
			lambda: review.set_review_comment_status(self.project.name, row["name"], "Resolved"),
			lambda: review.delete_review_comment(self.project.name, row["name"]),
			lambda: review.apply_review_comments(self.project.name),
		):
			with self.assertRaises(frappe.PermissionError):
				call()


def _row(start, end, text, status="Open", created="2026-01-01 00:00:00", english=None):
	return {
		"start_frame": start,
		"end_frame": end,
		"comment": text,
		"english": english or text,
		"status": status,
		"creation": created,
	}


class TestWording(FrappeTestCase):
	def test_requests_are_written_into_the_prompt_with_their_times(self):
		text = review.with_corrections(
			"A kid smiles.", [_row(24, 24, "Too dark"), _row(48, 71, "Mascot drifts")], 24
		)
		self.assertTrue(text.startswith("A kid smiles.\n\n" + review.CORRECTIONS_MARKER))
		self.assertIn("- at 1.0s: Too dark", text)
		self.assertIn("- from 2.0s to 3.0s: Mascot drifts", text)

	def test_the_block_is_rebuilt_not_stacked(self):
		once = review.with_corrections("A kid smiles.", [_row(0, 0, "Brighter")], 24)
		twice = review.with_corrections(once, [_row(0, 0, "Brighter"), _row(30, 40, "Hold the pack")], 24)
		self.assertEqual(1, twice.count(review.CORRECTIONS_MARKER))
		self.assertEqual(1, twice.count("Brighter"))
		self.assertEqual("A kid smiles.", review.strip_corrections(twice))

	def test_without_comments_the_original_prompt_comes_back(self):
		self.assertEqual(
			"A kid smiles.",
			review.with_corrections(review.with_corrections("A kid smiles.", [_row(0, 0, "x")], 24), [], 24),
		)

	def test_open_requests_are_never_dropped_and_old_ones_give_way(self):
		old = [_row(0, 0, "old " + "w" * 300, "Addressed", f"2026-01-0{n} 00:00:00") for n in range(1, 8)]
		new = _row(5, 5, "must stay", "Open", "2026-02-01 00:00:00")
		text = review.with_corrections("P", [*old, new], 24)
		self.assertIn("must stay", text)
		self.assertLessEqual(len(text) - 1, review.MAX_CORRECTIONS_CHARS + 10)
		self.assertLess(text.count("old "), 7)

	def test_open_requests_that_cannot_fit_are_refused_loudly(self):
		with self.assertRaises(frappe.ValidationError):
			review.with_corrections(
				"P", [_row(i, i, "x" * 400, created=f"2026-01-01 00:00:{i:02d}") for i in range(6)], 24
			)

	def test_the_approved_starting_picture_is_never_touched(self):
		shot = frappe._dict(generation_prompt="Video.", image_prompt="Picture.")
		with patch("joymedia.services.planning.llm.to_english", side_effect=lambda text: text):
			video = review.revised_generation_prompt(
				shot, [_row(0, 0, "Brighter look"), _row(60, 70, "Pack in hand")], 24
			)
		self.assertIn("Brighter look", video)
		self.assertIn("Pack in hand", video)
		self.assertEqual("Picture.", shot.image_prompt)

	def test_other_languages_are_put_into_english_for_the_model(self):
		shot = frappe._dict(generation_prompt="Video.", image_prompt="Picture.")
		with patch(
			"joymedia.services.planning.llm.to_english", return_value="Make the bear smile more"
		) as translate:
			video = review.revised_generation_prompt(shot, [_row(0, 0, "Cho gấu cười nhiều hơn")], 24)
		translate.assert_called_once_with("Cho gấu cười nhiều hơn")
		self.assertIn("Make the bear smile more", video)
		self.assertNotIn("gấu", video)


@patch("joymedia.services.planning.llm.to_english", side_effect=lambda text: text)
@patch("joymedia.services.generation.takes._ensure_scene_free")
@patch("joymedia.services.generation.takes.regenerate_scene_with_reason", return_value={"run": "RUN-X"})
class TestApplying(ReviewCommentCase):
	def test_open_comments_are_written_into_the_prompts_a_new_take_starts_and_the_comments_become_history(
		self, regenerate, free, english
	):
		first, second = self.add(start=0, text="Brighter"), self.add(start=10, end=20, text="Fix paws")
		result = review.apply_review_comments(self.project.name)

		self.assertEqual(1, result["applied"])
		video, picture = frappe.db.get_value("Shot", self.one.name, ["generation_prompt", "image_prompt"])
		self.assertEqual("Original.", picture)  # the approved first frame is not redrawn
		for wanted in ("Brighter", "Fix paws", "at 0.0s", "from 0.4s to 0.9s"):
			self.assertIn(wanted, video)
		self.assertTrue(video.startswith("Original."))
		regenerate.assert_called_once_with(self.project.name, self.one.name, retry_reason="QA Rejection")
		self.assertEqual(
			{"Addressed"},
			{frappe.db.get_value("Review Comment", n["name"], "status") for n in (first, second)},
		)

	def test_a_second_round_keeps_the_first_rounds_fixes_without_repeating_them(
		self, regenerate, free, english
	):
		self.add(start=0, text="Brighter")
		review.apply_review_comments(self.project.name)
		new_take = _create_output_version(
			self.project,
			"round2.mp4",
			3,
			frappe.get_doc("Media Asset", {"asset_name": f"{self.one.name} Output"}),
		)[1]
		self.one.db_set("selected_output_asset_version", new_take.name, update_modified=False)
		self.add(start=5, text="Smile more")
		review.apply_review_comments(self.project.name)
		video = frappe.db.get_value("Shot", self.one.name, "generation_prompt")
		self.assertEqual(
			(1, 1, 1),
			(video.count("Brighter"), video.count("Smile more"), video.count(review.CORRECTIONS_MARKER)),
		)

	def test_an_approved_storyboard_stays_approved_after_the_revision(self, regenerate, free, english):
		from joymedia.services.planning.signature import compute_plan_signature

		self.project.db_set(
			{
				"storyboard_approval_status": "Approved",
				"approved_plan_signature": compute_plan_signature(self.project.name),
			}
		)
		self.add()
		review.apply_review_comments(self.project.name)
		self.assertEqual(
			"Approved", frappe.db.get_value("Media Project", self.project.name, "storyboard_approval_status")
		)
		self.assertEqual(
			compute_plan_signature(self.project.name),
			frappe.db.get_value("Media Project", self.project.name, "approved_plan_signature"),
		)

	def test_a_failed_render_restores_the_prompts_and_the_approved_plan_exactly(
		self, regenerate, free, english
	):
		from joymedia.services.planning.signature import compute_plan_signature

		regenerate.side_effect = frappe.ValidationError("gpu busy")
		before = compute_plan_signature(self.project.name)
		self.project.db_set({"storyboard_approval_status": "Approved", "approved_plan_signature": before})
		row = self.add()
		result = review.apply_review_comments(self.project.name)
		self.assertFalse(result["scenes"][0]["applied"])
		self.assertEqual("Original.", frappe.db.get_value("Shot", self.one.name, "generation_prompt"))
		self.assertEqual(
			before, frappe.db.get_value("Media Project", self.project.name, "approved_plan_signature")
		)
		self.assertEqual("Open", frappe.db.get_value("Review Comment", row["name"], "status"))

	def test_applying_twice_does_not_render_twice(self, regenerate, free, english):
		self.add()
		review.apply_review_comments(self.project.name)
		with self.assertRaises(frappe.ValidationError):
			review.apply_review_comments(self.project.name)
		self.assertEqual(1, regenerate.call_count)

	def test_resolved_and_old_take_comments_are_left_out(self, regenerate, free, english):
		stale = self.add(text="old take")
		done = self.add(text="done by hand")
		review.set_review_comment_status(self.project.name, done["name"], "Resolved")
		new_take = _create_output_version(
			self.project,
			"third.mp4",
			3,
			frappe.get_doc("Media Asset", {"asset_name": f"{self.one.name} Output"}),
		)[1]
		self.one.db_set("selected_output_asset_version", new_take.name, update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			review.apply_review_comments(self.project.name)
		regenerate.assert_not_called()
		self.assertEqual("Open", frappe.db.get_value("Review Comment", stale["name"], "status"))

	def test_only_the_asked_scenes_are_applied(self, regenerate, free, english):
		self.add(shot=self.one)
		two = self.add(shot=self.two)
		review.apply_review_comments(self.project.name, [self.two.name])
		regenerate.assert_called_once_with(self.project.name, self.two.name, retry_reason="QA Rejection")
		self.assertEqual("Addressed", frappe.db.get_value("Review Comment", two["name"], "status"))
		self.assertEqual("Original.", frappe.db.get_value("Shot", self.one.name, "generation_prompt"))

	def test_a_busy_scene_stops_everything_before_any_change(self, regenerate, free, english):
		free.side_effect = [None, frappe.ValidationError("still rendering")]
		self.add(shot=self.one)
		self.add(shot=self.two)
		with self.assertRaises(frappe.ValidationError):
			review.apply_review_comments(self.project.name)
		self.assertEqual("Original.", frappe.db.get_value("Shot", self.one.name, "generation_prompt"))
		regenerate.assert_not_called()

	def test_a_scene_that_cannot_render_keeps_its_prompts_and_comments_while_the_others_go_ahead(
		self, regenerate, free, english
	):
		regenerate.side_effect = [frappe.ValidationError("gpu busy"), {"run": "RUN-2"}]
		a, b = self.add(shot=self.one), self.add(shot=self.two)
		result = review.apply_review_comments(self.project.name)

		self.assertEqual([False, True], [r["applied"] for r in result["scenes"]])
		self.assertIn("gpu busy", result["scenes"][0]["error"])
		self.assertEqual("Original.", frappe.db.get_value("Shot", self.one.name, "generation_prompt"))
		self.assertEqual("Open", frappe.db.get_value("Review Comment", a["name"], "status"))
		self.assertEqual("Addressed", frappe.db.get_value("Review Comment", b["name"], "status"))
		self.assertIn("Make it brighter.", frappe.db.get_value("Shot", self.two.name, "generation_prompt"))


class TestStress(ReviewCommentCase):
	def test_hundreds_of_comments_list_quickly_and_a_full_scene_gives_a_bounded_instruction(self):
		scenes = [self.one, self.two]
		for number in range(3, 11):
			scenes.append(_scene(self.project, number)[0])
		started = time.monotonic()
		for shot in scenes:
			for index in range(review.MAX_OPEN_PER_SCENE):
				review.add_review_comment(
					self.project.name, shot.name, f"Note {index} " + "word " * 50, index % self.limit
				)
		built = time.monotonic() - started
		started = time.monotonic()
		rows = review.get_review_comments(self.project.name)
		listed = time.monotonic() - started
		self.assertEqual(len(scenes) * review.MAX_OPEN_PER_SCENE, len(rows))
		self.assertLess(
			listed, 3.0, f"listing {len(rows)} comments took {listed:.2f}s (adding took {built:.1f}s)"
		)
		one_scene = [r for r in rows if r["shot"] == self.one.name]
		wording = review.with_corrections(
			"P", [{**r, "english": r["comment"], "creation": r["created"]} for r in one_scene[:3]], self.fps
		)
		self.assertLessEqual(len(wording), review.MAX_CORRECTIONS_CHARS + 50)


class TestWholeSceneComments(ReviewCommentCase):
	def test_a_comment_can_be_about_the_whole_scene(self):
		row = review.add_review_comment(
			self.project.name, self.one.name, "Warmer light overall", whole_scene=1
		)
		self.assertEqual(
			("Scene", None, None, None),
			(row["scope"], row["start_frame"], row["end_frame"], row["start_seconds"]),
		)

	def test_whole_scene_requests_come_first_in_the_prompt(self):
		text = review.with_corrections(
			"P",
			[
				_row(10, 10, "Fix the paw", created="2026-01-02 00:00:00"),
				{**_row(None, None, "Warmer light overall", created="2026-01-03 00:00:00"), "scope": "Scene"},
			],
			24,
		)
		self.assertLess(
			text.index("for the whole scene: Warmer light overall"), text.index("at 0.4s: Fix the paw")
		)

	@patch("joymedia.services.planning.llm.to_english", side_effect=lambda text: text)
	@patch("joymedia.services.generation.takes._ensure_scene_free")
	@patch("joymedia.services.generation.takes.regenerate_scene_with_reason", return_value={"run": "RUN-X"})
	def test_whole_scene_and_frame_comments_are_applied_together(self, regenerate, free, english):
		review.add_review_comment(self.project.name, self.one.name, "Warmer light overall", whole_scene=1)
		self.add(start=5, text="Fix the paw")
		review.apply_review_comments(self.project.name)
		video = frappe.db.get_value("Shot", self.one.name, "generation_prompt")
		self.assertIn("for the whole scene: Warmer light overall", video)
		self.assertIn("Fix the paw", video)
