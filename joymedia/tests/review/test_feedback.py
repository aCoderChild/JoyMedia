import json

import frappe

from joymedia.services.review import feedback
from joymedia.tests.review.test_comments import ReviewCommentCase


class TestVideoFeedback(ReviewCommentCase):
	def test_point_marker_round_trips_and_cannot_be_rewritten(self):
		point = {"type": "point", "x": 0.25, "y": 0.75}
		row = self.add_feedback(annotation_json=point)
		self.assertEqual(row["annotation"], point)
		loaded = feedback.get_feedback(self.project.name, self.one_take.name, focused_name=row["name"])
		self.assertEqual(loaded["focused"]["annotation"], point)
		doc = frappe.get_doc("Video Review Feedback", row["name"])
		doc.annotation_json = json.dumps({**point, "x": 0.5})
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_annotation_protocol_rejects_invalid_point_coordinates_and_shape_fields(self):
		for value in (True, None, "0.5", float("nan"), float("inf"), -0.1, 1.1, [], {}):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				feedback.annotation({"type": "point", "x": value, "y": 0.5})
		for point in (
			{"type": "point", "x": 0.5},
			{"type": "point", "x": 0.5, "y": 0.5, "width": 0.2},
			{"type": "script", "x": 0.5, "y": 0.5},
		):
			with self.subTest(point=point), self.assertRaises(frappe.ValidationError):
				feedback.annotation(point)
		for x in (0, 1):
			self.assertEqual(
				feedback.annotation({"type": "point", "x": x, "y": x}), {"type": "point", "x": x, "y": x}
			)
		with self.assertRaises(frappe.ValidationError):
			feedback.annotation({"x": True, "y": 0, "width": 0.2, "height": 0.2})

	def add_feedback(self, **kwargs):
		return feedback.add_feedback(
			self.project.name,
			self.one_take.name,
			"The hand is disconnected.",
			frappe.generate_hash(length=24),
			start_frame=5,
			**kwargs,
		)

	def test_exact_version_frame_author_and_normalized_annotation_are_saved(self):
		row = self.add_feedback(
			annotation_json={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}, category="Anatomy"
		)
		doc = frappe.get_doc("Video Review Feedback", row["name"])
		self.assertEqual(
			(doc.media_project, doc.source_edit, doc.asset_version, doc.shot, doc.owner),
			(self.project.name, self.project.name, self.one_take.name, self.one.name, "Administrator"),
		)
		self.assertEqual((doc.start_frame, doc.end_frame, doc.scope), (5, 5, "Frame"))
		self.assertEqual(row["start_seconds"], 5 / doc.fps)
		self.assertEqual(row["annotation"], json.loads(doc.annotation_json))

	def test_closed_filter_paginates_open_comments_but_explicit_links_still_work(self):
		closed = self.add_feedback()
		feedback.triage_feedback(closed["name"], "Dismissed", "Automated verification")
		active = self.add_feedback()
		result = feedback.get_feedback(
			self.project.name, self.one_take.name, include_closed=False, focused_name=closed["name"]
		)
		self.assertEqual([row["name"] for row in result["items"]], [active["name"]])
		self.assertEqual(result["focused"]["name"], closed["name"])
		self.assertEqual(len(feedback.get_feedback(self.project.name, self.one_take.name)["items"]), 2)

	def test_retry_is_idempotent_and_changed_payload_is_rejected(self):
		key = frappe.generate_hash(length=24)
		one = feedback.add_feedback(self.project.name, self.one_take.name, "Wrong logo", key, start_frame=0)
		two = feedback.add_feedback(self.project.name, self.one_take.name, "Wrong logo", key, start_frame=0)
		self.assertEqual(one["name"], two["name"])
		with self.assertRaises(frappe.ValidationError):
			feedback.add_feedback(self.project.name, self.one_take.name, "Different text", key, start_frame=0)

	def test_historical_take_is_reviewable_after_selection_changes(self):
		self.one.db_set("selected_output_asset_version", None, update_modified=False)
		row = self.add_feedback()
		self.assertEqual(row["asset_version"], self.one_take.name)
		self.assertIsNone(frappe.db.get_value("Shot", self.one.name, "selected_output_asset_version"))

	def test_whole_video_and_ranges(self):
		whole = feedback.add_feedback(
			self.project.name, self.one_take.name, "Review the pacing.", frappe.generate_hash(length=24)
		)
		self.assertEqual(whole["scope"], "Video")
		self.assertIsNone(whole["start_frame"])
		row = self.add_feedback(end_frame=12)
		self.assertEqual((row["scope"], row["start_frame"], row["end_frame"]), ("Range", 5, 12))

	def test_bad_ranges_and_areas_are_rejected(self):
		for start, end in [(-1, 0), (0, 99999), (5, 2), (1.5, 2), ("NaN", 1), (None, 2)]:
			with self.subTest(start=start, end=end), self.assertRaises(frappe.ValidationError):
				feedback.add_feedback(
					self.project.name,
					self.one_take.name,
					"Invalid",
					frappe.generate_hash(length=24),
					start_frame=start,
					end_frame=end,
				)
		for box in [
			{"x": 0, "y": 0, "width": 2, "height": 0.2},
			{"x": 0, "y": 0, "width": 0, "height": 0.2},
			{"x": "NaN", "y": 0, "width": 0.2, "height": 0.2},
			{"svg": "<script>"},
		]:
			with self.subTest(box=box), self.assertRaises(frappe.ValidationError):
				self.add_feedback(annotation_json=box)

	def test_markup_is_stripped_and_classification_is_validated(self):
		row = feedback.add_feedback(
			self.project.name, self.one_take.name, "<b>Wrong logo</b>", frappe.generate_hash(length=24)
		)
		self.assertEqual(row["feedback"], "Wrong logo")
		for kwargs in [
			{"category": "Invented"},
			{"priority": "Urgent"},
			{"annotation_json": {"x": 0, "y": 0, "width": 0.2, "height": 0.2}},
		]:
			with self.assertRaises(frappe.ValidationError):
				feedback.add_feedback(
					self.project.name, self.one_take.name, "Issue", frappe.generate_hash(length=24), **kwargs
				)

	def test_foreign_project_and_anonymous_access_are_rejected(self):
		other = frappe.copy_doc(self.project).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			feedback.get_feedback(other.name, self.one_take.name)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			feedback.get_feedback(self.project.name, self.one_take.name)
		with self.assertRaises(frappe.PermissionError):
			feedback.triage_feedback("does-not-exist", "Resolved")

	def test_admin_triage_preserves_original_evidence(self):
		row = self.add_feedback()
		updated = feedback.triage_feedback(row["name"], "Resolved", "Fixed in the next pipeline.")
		self.assertEqual(
			(updated["status"], updated["admin_response"]), ("Resolved", "Fixed in the next pipeline.")
		)
		doc = frappe.get_doc("Video Review Feedback", row["name"])
		self.assertEqual(doc.resolved_by, "Administrator")
		doc.feedback = "Rewritten evidence"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_filtering_pagination_and_deep_link_cannot_cross_versions(self):
		rows = [self.add_feedback() for _ in range(3)]
		first = feedback.get_feedback(self.project.name, self.one_take.name, page_length=1)
		self.assertEqual(len(first["items"]), 1)
		self.assertTrue(first["has_more"])
		second = feedback.get_feedback(self.project.name, self.one_take.name, start=1, page_length=1)
		self.assertNotEqual(first["items"][0]["name"], second["items"][0]["name"])
		self.assertIsNotNone(
			feedback.get_feedback(self.project.name, self.one_take.name, focused_name=rows[-1]["name"])[
				"focused"
			]
		)
		empty = feedback.get_feedback(self.project.name, self.two_take.name, focused_name=rows[-1]["name"])
		self.assertEqual(empty["items"], [])
		self.assertIsNone(empty["focused"])

	def test_full_export_is_reviewable_and_archiving_does_not_destroy_feedback(self):
		asset = frappe.copy_doc(frappe.get_doc("Media Asset", self.one_take.media_asset))
		asset.asset_name = f"{self.project.name} Final Video"
		asset.insert(ignore_permissions=True)
		version = frappe.copy_doc(self.one_take)
		version.media_asset = asset.name
		version.insert(ignore_permissions=True)
		row = feedback.add_feedback(
			self.project.name,
			version.name,
			"Whole film needs a better ending.",
			frappe.generate_hash(length=24),
		)
		self.assertIsNone(row["shot"])
		self.project.db_set("status", "Archived")
		self.assertEqual(
			feedback.get_feedback(self.project.name, version.name)["items"][0]["name"], row["name"]
		)
