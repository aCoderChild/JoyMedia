import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.timeline_editor import (
	_invalidate_project_output,
	delete_timeline_clip,
	duplicate_timeline_clip,
	reorder_timeline_clip,
	split_timeline_clip,
	sync_timeline_source_for_shot,
	trim_timeline_clip,
)


def _generate_video_bytes(seconds=4):
	with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
		subprocess.run(
			[
				"ffmpeg",
				"-v",
				"error",
				"-y",
				"-f",
				"lavfi",
				"-i",
				f"color=c=black:s=320x240:r=24:d={seconds}",
				"-an",
				"-c:v",
				"libx264",
				"-pix_fmt",
				"yuv420p",
				tmp.name,
			],
			check=True,
		)
		return Path(tmp.name).read_bytes()


class TestTimelineEditor(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.campaign = frappe.get_doc(
			{
				"doctype": "Campaign",
				"campaign_name": "Test Campaign",
				"product_name": "Test Product",
			}
		).insert(ignore_permissions=True)

		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Test Timeline Project",
				"campaign": self.campaign.name,
				"status": "Draft",
			}
		).insert(ignore_permissions=True)

		self.spec = frappe.get_doc(
			{
				"doctype": "Media Specification",
				"media_project": self.project.name,
				"version_number": 1,
				"fps": 24,
				"total_duration_seconds": 10,
			}
		).insert(ignore_permissions=True)

		self.asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": "Test Source Video",
				"media_type": "Video",
				"asset_category": "Product",
				"status": "Active",
			}
		).insert(ignore_permissions=True)

		self.file_doc_1 = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "test-v1.mp4",
				"content": _generate_video_bytes(4),
				"is_private": 1,
				"attached_to_doctype": "Media Asset",
				"attached_to_name": self.asset.name,
			}
		).insert(ignore_permissions=True)

		self.version_1 = frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": self.asset.name,
				"file": self.file_doc_1.file_url,
				"source": "Generated",
				"duration_seconds": 4.0,
				"fps": 24,
			}
		).insert(ignore_permissions=True)

		self.shot = frappe.get_doc(
			{
				"doctype": "Shot Specification",
				"media_specification": self.spec.name,
				"shot_number": 1,
				"subject_identity": "Product Hero",
				"action_plot": "Close-up cinematic rotation",
				"planned_frame_count": 96,
				"duration_seconds": 4.0,
			}
		).insert(ignore_permissions=True)
		self.shot.db_set("selected_output_asset_version", self.version_1.name, update_modified=False)

		self.clip_1 = frappe.get_doc(
			{
				"doctype": "Timeline Clip",
				"media_project": self.project.name,
				"media_specification": self.spec.name,
				"shot_specification": self.shot.name,
				"clip_order": 1,
				"enabled": 1,
				"source_asset_version": self.version_1.name,
				"source_in_frame": 0,
				"source_out_frame": 96,
				"initial_source_in_frame": 0,
				"initial_source_out_frame": 96,
				"transition_to_next": "Cut",
				"transition_frames": 0,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_trim_timeline_clip_updates_range_and_invalidates_output(self):
		frappe.db.set_value(
			"Media Project",
			self.project.name,
			"current_output_asset_version",
			self.version_1.name,
			update_modified=False,
		)

		res = trim_timeline_clip(self.project.name, self.clip_1.name, 10, 80)
		self.clip_1.reload()

		self.assertEqual(self.clip_1.source_in_frame, 10)
		self.assertEqual(self.clip_1.source_out_frame, 80)
		current_out = frappe.db.get_value(
			"Media Project", self.project.name, "current_output_asset_version"
		)
		self.assertIsNone(current_out)

	def test_split_timeline_clip_preserves_source_asset_and_invalidates(self):
		frappe.db.set_value(
			"Media Project",
			self.project.name,
			"current_output_asset_version",
			self.version_1.name,
			update_modified=False,
		)

		res = split_timeline_clip(self.project.name, self.clip_1.name, 48)
		self.clip_1.reload()

		self.assertEqual(self.clip_1.source_in_frame, 0)
		self.assertEqual(self.clip_1.source_out_frame, 48)

		clips = frappe.get_all(
			"Timeline Clip",
			filters={"media_project": self.project.name},
			fields=["name", "source_asset_version", "source_in_frame", "source_out_frame", "clip_order"],
			order_by="clip_order asc",
		)
		self.assertEqual(len(clips), 2)
		self.assertEqual(clips[1].source_asset_version, self.version_1.name)
		self.assertEqual(clips[1].source_in_frame, 48)
		self.assertEqual(clips[1].source_out_frame, 96)

		current_out = frappe.db.get_value(
			"Media Project", self.project.name, "current_output_asset_version"
		)
		self.assertIsNone(current_out)

	def test_duplicate_timeline_clip_creates_instance(self):
		res = duplicate_timeline_clip(self.project.name, self.clip_1.name)
		clips = frappe.get_all(
			"Timeline Clip",
			filters={"media_project": self.project.name},
			fields=["name", "source_asset_version", "source_in_frame", "source_out_frame", "clip_order"],
			order_by="clip_order asc",
		)
		self.assertEqual(len(clips), 2)
		self.assertEqual(clips[0].clip_order, 1)
		self.assertEqual(clips[1].clip_order, 2)
		self.assertEqual(clips[1].source_asset_version, self.version_1.name)

	def test_reorder_timeline_clip_updates_sequence(self):
		duplicate_timeline_clip(self.project.name, self.clip_1.name)
		clips = frappe.get_all(
			"Timeline Clip",
			filters={"media_project": self.project.name},
			order_by="clip_order asc",
		)
		second_clip = clips[1].name

		reorder_timeline_clip(self.project.name, second_clip, 1)

		reloaded_clips = frappe.get_all(
			"Timeline Clip",
			filters={"media_project": self.project.name},
			fields=["name", "clip_order"],
			order_by="clip_order asc",
		)
		self.assertEqual(reloaded_clips[0].name, second_clip)
		self.assertEqual(reloaded_clips[0].clip_order, 1)

	def test_sync_timeline_source_for_shot_updates_clip_source(self):
		file_doc_2 = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "test-v2.mp4",
				"content": _generate_video_bytes(3),
				"is_private": 1,
				"attached_to_doctype": "Media Asset",
				"attached_to_name": self.asset.name,
			}
		).insert(ignore_permissions=True)

		version_2 = frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": self.asset.name,
				"file": file_doc_2.file_url,
				"source": "Generated",
				"duration_seconds": 3.0,
				"fps": 24,
			}
		).insert(ignore_permissions=True)

		self.shot.db_set("selected_output_asset_version", version_2.name, update_modified=False)

		frappe.db.set_value(
			"Media Project",
			self.project.name,
			"current_output_asset_version",
			self.version_1.name,
			update_modified=False,
		)

		sync_timeline_source_for_shot(self.shot.name)
		self.clip_1.reload()

		self.assertEqual(self.clip_1.source_asset_version, version_2.name)
		# 3.0s * 24 = 72 frames max
		self.assertEqual(self.clip_1.source_out_frame, 72)

		current_out = frappe.db.get_value(
			"Media Project", self.project.name, "current_output_asset_version"
		)
		self.assertIsNone(current_out)

	def test_final_video_fallback_and_invalidation(self):
		from joymedia.services.timeline_editor import _final_video

		# 1. Create a Generation Run with final_asset_version = version_1
		run = frappe.get_doc(
			{
				"doctype": "Generation Run",
				"media_specification": self.spec.name,
				"final_asset_version": self.version_1.name,
				"status": "Completed",
			}
		).insert(ignore_permissions=True)

		# No project output yet -> falls back to Generation Run master
		video = _final_video(self.project.name, self.spec.name)
		self.assertIsNotNone(video)
		self.assertEqual(video["name"], self.version_1.name)

		# 2. Simulate export -> sets Media Project.current_output_asset_version
		file_doc_export = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "test-export.mp4",
				"content": _generate_video_bytes(4),
				"is_private": 1,
				"attached_to_doctype": "Media Asset",
				"attached_to_name": self.asset.name,
			}
		).insert(ignore_permissions=True)

		version_export = frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": self.asset.name,
				"file": file_doc_export.file_url,
				"source": "Edited",
				"duration_seconds": 4.0,
				"fps": 24,
			}
		).insert(ignore_permissions=True)

		frappe.db.set_value(
			"Media Project",
			self.project.name,
			"current_output_asset_version",
			version_export.name,
			update_modified=False,
		)

		video = _final_video(self.project.name, self.spec.name)
		self.assertEqual(video["name"], version_export.name)

		# 3. User edits timeline -> invalidation happens
		trim_timeline_clip(self.project.name, self.clip_1.name, 5, 75)
		video = _final_video(self.project.name, self.spec.name)
		# Should fall back to Generation Run master again
		self.assertEqual(video["name"], self.version_1.name)
