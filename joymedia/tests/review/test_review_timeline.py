import json
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.review.timeline import get_review_timeline, rendered_segments, timeline_from_manifest


class TestReviewTimeline(TestCase):
	def test_dissolves_follow_rendered_time_instead_of_the_current_plan(self):
		clips = [{"shot": "a", "timeline_start_frame": 999}, {"shot": "b", "timeline_start_frame": 999}]
		scenes = [{"name": "a", "shot_name": "Opening"}, {"name": "b", "shot_name": "Action"}]
		rows = rendered_segments(clips, [96, 72], [12], False, 24, scenes)
		self.assertEqual([(r["start_seconds"], r["end_seconds"]) for r in rows], [(0, 4), (3.5, 6.5)])
		self.assertEqual(rows[1]["title"], "Action")
		result = timeline_from_manifest({"render_timeline": {"segments": rows}}, 48, 312)
		self.assertEqual((result[1]["start_frame"], result[1]["end_frame"]), (168, 312))

	def test_positioned_gaps_and_trimmed_footage_keep_render_positions(self):
		rows = rendered_segments(
			[{"timeline_start_frame": 24}, {"timeline_start_frame": 120}], [48, 24], [0], True, 24, []
		)
		self.assertEqual([(r["start_seconds"], r["end_seconds"]) for r in rows], [(1, 3), (5, 6)])

	def test_legacy_exports_never_invent_scene_boundaries(self):
		for manifest in (None, "", {}, "bad", {"clips": [{"shot": "a"}]}):
			self.assertEqual(timeline_from_manifest(manifest, 24, 720), [])

	def test_malformed_and_nonfinite_timing_fail_closed(self):
		for row in (
			None,
			5,
			[],
			{"start_seconds": -1, "end_seconds": 4},
			{"start_seconds": 2, "end_seconds": 1},
			{"start_seconds": 0, "end_seconds": float("inf")},
		):
			self.assertEqual(timeline_from_manifest({"render_timeline": {"segments": [row]}}, 24, 720), [])

	def test_bounds_are_clipped_to_the_actual_export(self):
		rows = timeline_from_manifest(
			json.dumps(
				{"render_timeline": {"segments": [{"start_seconds": 1, "end_seconds": 50, "title": "Last"}]}}
			),
			24,
			720,
		)
		self.assertEqual((rows[0]["start_frame"], rows[0]["end_frame"]), (24, 720))

	def test_endpoint_uses_exact_version_authorization_and_hides_internal_directions(self):
		version = frappe._dict(
			name="old",
			edit_manifest_json=json.dumps(
				{
					"render_timeline": {
						"segments": [
							{
								"start_seconds": 0,
								"end_seconds": 2,
								"title": "Old scene",
								"direction": "Internal",
							}
						]
					}
				}
			),
		)
		with (
			patch(
				"joymedia.services.review.feedback.target", return_value=(None, None, version, None, 24, 48)
			) as authorized,
			patch("joymedia.services.partners.is_reviewer", return_value=True),
			patch.object(frappe, "get_all", return_value=[]) as markers,
		):
			data = get_review_timeline("project", "old")
		authorized.assert_called_once_with("project", "old")
		self.assertEqual(data["asset_version"], "old")
		self.assertEqual(data["segments"][0]["title"], "Old scene")
		self.assertNotIn("direction", data["segments"][0])
		self.assertEqual(markers.call_args.kwargs["filters"]["owner"], frappe.session.user)

	def test_unauthorized_versions_cannot_read_timeline_metadata(self):
		with patch("joymedia.services.review.feedback.target", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				get_review_timeline("project", "hidden")
