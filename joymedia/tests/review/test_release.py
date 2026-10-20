from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.review.brand import approval_signature
from joymedia.services.review.release import release_evidence


class TestReleaseEvidence(TestCase):
	def setUp(self):
		guard = patch('joymedia.services.review.release_feedback.unresolved_cut_feedback', return_value=[])
		self.cut_feedback = guard.start()
		self.addCleanup(guard.stop)
		self.references = [frappe._dict(reference_role="Product", asset_version="SOURCE")]
		self.shot = frappe._dict(
			name="SHOT",
			selected_output_asset_version="TAKE",
			brand_approval_signature=approval_signature("TAKE", self.references),
			brand_approved_by="reviewer",
			brand_approved_at="2026-10-15",
		)
		self.clip = {"name": "CLIP", "shot": "SHOT", "source_asset_version": "TAKE", "track_type": "Video"}

	def run_guard(self, clips=None, open_comments=False):
		with (
			patch('joymedia.services.review.lineage.take_direction_changed', return_value=False),
			patch.object(frappe.db, "sql", side_effect=[[self.shot], self.references]),
			patch.object(frappe.db, "exists", return_value=open_comments),
		):
			return release_evidence("PROJECT", [self.clip] if clips is None else clips)

	def test_review_is_bound_to_the_actual_export_source(self):
		self.assertEqual(self.run_guard()["clips"][0]["take"], "TAKE")
		with self.assertRaisesRegex(ValueError, "without current scene approval"):
			self.run_guard([{**self.clip, "source_asset_version": "OLDER-TAKE"}])

	def test_action_pass_or_a_new_reference_does_not_approve_release(self):
		self.shot.brand_approval_signature = ""
		with self.assertRaisesRegex(ValueError, "identity review"):
			self.run_guard()
		self.shot.brand_approval_signature = approval_signature("TAKE", self.references)
		self.references[0].asset_version = "NEW-SOURCE"
		with self.assertRaisesRegex(ValueError, "identity review"):
			self.run_guard()

	def test_open_review_comments_block_release(self):
		with self.assertRaisesRegex(ValueError, "unresolved review comments"):
			self.run_guard(open_comments=True)

	def test_unassigned_footage_cannot_inherit_another_scenes_approval(self):
		with self.assertRaisesRegex(ValueError, "without current scene approval"):
			self.run_guard([{**self.clip, "shot": None}])

	def test_audio_and_disabled_clips_cannot_supply_release_evidence(self):
		with self.assertRaisesRegex(ValueError, "requires reviewed scene footage"):
			self.run_guard([{**self.clip, "track_type": "Audio"}, {**self.clip, "enabled": 0}])

	def test_unresolved_frame_feedback_blocks_the_exact_scene_take(self):
		with (
			patch('joymedia.services.review.lineage.take_direction_changed', return_value=False),
			patch.object(frappe.db, 'sql', side_effect=[[self.shot], self.references]),
			patch.object(frappe.db, 'exists', side_effect=lambda doctype, filters: doctype == 'Video Review Feedback'),
		):
			with self.assertRaisesRegex(ValueError, 'unresolved frame or timeline feedback'):
				release_evidence('PROJECT', [self.clip])

	def test_a_new_direction_cannot_be_released_with_old_footage(self):
		with (
			patch('joymedia.services.review.lineage.take_direction_changed', return_value=True),
			patch.object(frappe.db, 'sql', side_effect=[[self.shot], self.references]),
			patch.object(frappe.db, 'exists', return_value=False),
		):
			with self.assertRaisesRegex(ValueError, 'earlier direction'):
				release_evidence('PROJECT', [self.clip])

	def test_full_cut_findings_are_not_bypassed_by_reexport(self):
		self.cut_feedback.return_value = ['FINDING']
		with self.assertRaisesRegex(ValueError, 'Full-video feedback still needs review'):
			self.run_guard()
