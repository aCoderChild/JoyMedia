import json
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.review.release_feedback import affected_sources, unresolved_cut_feedback


class TestCutFeedback(TestCase):
	def setUp(self):
		self.manifest = {
			"render_timeline": {
				"segments": [
					{"start_seconds": 0, "end_seconds": 4, "source_asset_version": "A"},
					{"start_seconds": 3.5, "end_seconds": 7, "source_asset_version": "B"},
				]
			}
		}
		self.feedback = frappe._dict(
			name="ISSUE",
			scope="Frame",
			start_frame=24,
			end_frame=24,
			fps=24,
			edit_manifest_json=json.dumps(self.manifest),
		)

	def test_dissolve_marks_both_sources(self):
		self.feedback.start_frame = self.feedback.end_frame = 90
		self.assertEqual(affected_sources(self.manifest, self.feedback), {"A", "B"})

	def test_exact_boundary_does_not_mark_ended_source(self):
		self.feedback.start_frame = self.feedback.end_frame = 96
		self.assertEqual(affected_sources(self.manifest, self.feedback), {"B"})

	def test_range_and_whole_video(self):
		self.feedback.end_frame = 120
		self.assertEqual(affected_sources(self.manifest, self.feedback), {"A", "B"})
		self.feedback.scope = "Video"
		self.feedback.fps = None
		self.assertIsNone(affected_sources(self.manifest, self.feedback))

	def test_whole_cut_audio_cannot_be_resolved_by_replacing_visual_takes(self):
		self.feedback.scope = "Video"
		self.assertEqual(self.check("NEW"), ["ISSUE"])

	def test_missing_or_invalid_evidence_never_means_fixed(self):
		for bad in [
			None,
			"{}",
			"[]",
			"{",
			{"render_timeline": {"segments": []}},
			{
				"render_timeline": {
					"segments": [dict(start_seconds=0, end_seconds=float("nan"), source_asset_version="A")]
				}
			},
		]:
			self.assertIsNone(affected_sources(bad, self.feedback))
		self.feedback.fps = 0
		self.assertIsNone(affected_sources(self.manifest, self.feedback))

	def check(self, source, *, ancestry=None, rows=None):
		def value(doctype, name, field):
			return "ROOT" if doctype == "Media Project" else (ancestry or {}).get(name)

		with (
			patch.object(frappe.db, "get_value", side_effect=value),
			patch.object(
				frappe.db,
				"sql",
				return_value=[self.feedback] if rows is None else rows,
			) as query,
		):
			result = unresolved_cut_feedback("EDIT", [{"source_asset_version": source}], lock=True)
			self.assertEqual(query.call_args.args[1], "ROOT")
			self.assertIn("for update", query.call_args.args[0])
			return result

	def test_unchanged_or_copied_affected_take_remains_blocked(self):
		self.assertEqual(self.check("A"), ["ISSUE"])
		self.assertEqual(self.check("COPY", ancestry={"COPY": "A"}), ["ISSUE"])

	def test_replaced_or_unaffected_take_is_not_blocked_by_old_finding(self):
		self.assertEqual(self.check("NEW"), [])
		self.assertEqual(self.check("B"), [])
		self.assertEqual(self.check("A", rows=[]), [])

	def test_unknown_timing_requires_explicit_triage(self):
		self.feedback.edit_manifest_json = "{}"
		self.assertEqual(self.check("NEW"), ["ISSUE"])

	def test_corrupt_lineage_cannot_bypass_review(self):
		with self.assertRaisesRegex(ValueError, "cyclic"):
			self.check("COPY", ancestry={"COPY": "COPY"})

	def test_disabled_clips_and_audio_cannot_supply_reused_video(self):
		with patch.object(frappe.db, "sql") as query:
			self.assertEqual(
				unresolved_cut_feedback(
					"EDIT",
					[
						{"source_asset_version": "A", "enabled": 0},
						{"source_asset_version": "A", "track_type": "Audio"},
					],
				),
				[],
			)
			query.assert_not_called()
