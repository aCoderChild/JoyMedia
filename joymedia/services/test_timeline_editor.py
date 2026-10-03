import json
import subprocess
import tempfile
from unittest.mock import patch
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.timeline_editor import (
	duplicate_timeline_clip,
	add_timeline_audio_clip,
	delete_timeline_clip,
	fit_audio_clip_to_full_video,
	fit_audio_clip_to_video,
	reorder_timeline_clip,
	reset_timeline_clip,
	set_timeline_transition,
	set_source_audio_enabled,
	set_audio_clip_enabled,
	restore_timeline_state,
	use_full_audio_source,
	split_timeline_clip,
	sync_timeline_source_for_shot,
	trim_timeline_clip,
	update_timeline_source_for_shot,
	move_timeline_clip,
)


def _generate_video_bytes(seconds=4):
	with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
		subprocess.run(
			[
				"ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
				f"color=c=black:s=320x240:r=24:d={seconds}", "-an", "-c:v", "libx264",
				"-pix_fmt", "yuv420p", tmp.name,
			],
			check=True,
		)
		return Path(tmp.name).read_bytes()


def _generate_audio_bytes(seconds=6):
	with tempfile.NamedTemporaryFile(suffix=".flac") as tmp:
		subprocess.run(
			[
				"ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
				f"sine=frequency=440:duration={seconds}", "-c:a", "flac", tmp.name,
			],
			check=True,
		)
		return Path(tmp.name).read_bytes()


class TestTimelineEditor(FrappeTestCase):
	def setUp(self):
		super().setUp()
		workflow = _create_workflow()
		self.project = frappe.get_doc({
			"doctype": "Media Project",
			"project_name": "Test Timeline Project",
			"product_name": "Test Product",
			"video_idea": "Create a product timeline test.",
			"total_duration_seconds": 10,
			"delivery_preset": "Landscape",
			"delivery_width": 1920,
			"delivery_height": 1080,
			"generation_mode": "Multi-shot",
			"workflow": workflow,
		}).insert(ignore_permissions=True)
		self.asset, self.version_1 = _create_output_version(self.project, "test-v1.mp4", 4)
		self.shot = frappe.get_doc({
			"doctype": "Shot",
			"media_project": self.project.name,
			"shot_number": 1,
			"shot_name": "Product Hero",
			"generation_prompt": "Close-up cinematic product rotation.",
			"duration_seconds": 4.0,
		}).insert(ignore_permissions=True)
		self.shot.db_set("selected_output_asset_version", self.version_1.name, update_modified=False)
		self.clip_1 = frappe.get_doc({
			"doctype": "Timeline Clip",
			"media_project": self.project.name,
			"shot": self.shot.name,
			"clip_order": 1,
			"enabled": 1,
			"source_asset_version": self.version_1.name,
			"source_in_frame": 0,
			"source_out_frame": 96,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": 96,
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_trim_updates_range_and_invalidates_project_output(self):
		frappe.db.set_value("Media Project", self.project.name, "current_output_asset_version", self.version_1.name)
		trim_timeline_clip(self.project.name, self.clip_1.name, 10, 80)
		self.clip_1.reload()
		self.assertEqual((self.clip_1.source_in_frame, self.clip_1.source_out_frame), (10, 80))
		self.assertIsNone(frappe.db.get_value("Media Project", self.project.name, "current_output_asset_version"))

	def test_audio_left_trim_moves_timeline_start_but_right_trim_does_not(self):
		audio_clip = frappe.get_doc({
			"doctype": "Timeline Clip",
			"media_project": self.project.name,
			"clip_order": 2,
			"track_type": "Audio",
			"timeline_start_frame": 24,
			"initial_timeline_start_frame": 24,
			"enabled": 1,
			"source_asset_version": self.version_1.name,
			"source_in_frame": 0,
			"source_out_frame": 96,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": 96,
			"audio_role": "BGM",
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}).insert(ignore_permissions=True)

		trim_timeline_clip(self.project.name, audio_clip.name, 12, 96)
		audio_clip.reload()
		self.assertEqual(audio_clip.timeline_start_frame, 36)

		trim_timeline_clip(self.project.name, audio_clip.name, 12, 72)
		audio_clip.reload()
		self.assertEqual(audio_clip.timeline_start_frame, 36)

		reset_timeline_clip(self.project.name, audio_clip.name)
		audio_clip.reload()
		self.assertEqual(audio_clip.timeline_start_frame, 24)

	def test_source_audio_cannot_be_fit_to_video(self):
		audio_clip = frappe.get_doc({
			"doctype": "Timeline Clip",
			"media_project": self.project.name,
			"clip_order": 2,
			"track_type": "Audio",
			"timeline_start_frame": 0,
			"enabled": 1,
			"source_asset_version": self.version_1.name,
			"source_in_frame": 0,
			"source_out_frame": 96,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": 96,
			"audio_role": "Source",
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			fit_audio_clip_to_video(self.project.name, audio_clip.name)

	def test_bgm_can_fit_to_full_video_from_current_position(self):
		audio_clip = frappe.get_doc({
			"doctype": "Timeline Clip",
			"media_project": self.project.name,
			"clip_order": 2,
			"track_type": "Audio",
			"timeline_start_frame": 120,
			"enabled": 1,
			"source_asset_version": self.version_1.name,
			"source_in_frame": 24,
			"source_out_frame": 48,
			"initial_source_in_frame": 24,
			"initial_source_out_frame": 48,
			"audio_role": "BGM",
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}).insert(ignore_permissions=True)

		fit_audio_clip_to_full_video(self.project.name, audio_clip.name)
		audio_clip.reload()
		self.assertEqual(audio_clip.timeline_start_frame, 0)
		self.assertEqual(audio_clip.source_out_frame, 96)

		result = set_audio_clip_enabled(self.project.name, audio_clip.name, False)
		added = next(clip for clip in result["clips"] if clip["name"] == audio_clip.name)
		self.assertFalse(added["enabled"])
		use_full_audio_source(self.project.name, audio_clip.name)
		audio_clip.reload()
		self.assertEqual((audio_clip.source_in_frame, audio_clip.source_out_frame), (0, 96))
		self.assertFalse(audio_clip.enabled)

	def test_new_audio_clip_keeps_source_duration_beyond_video_end(self):
		audio_asset = frappe.get_doc({
			"doctype": "Media Asset",
			"asset_name": "Test Long Audio",
			"media_type": "Audio",
			"asset_category": "Audio",
			"asset_scope": "Project Output",
			"media_project": self.project.name,
			"status": "Active",
		}).insert(ignore_permissions=True)
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": "test-long-audio.flac",
			"content": _generate_audio_bytes(),
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": audio_asset.name,
		}).insert(ignore_permissions=True)
		audio_version = frappe.get_doc({
			"doctype": "Asset Version",
			"media_asset": audio_asset.name,
			"file": file_doc.file_url,
			"source": "Uploaded",
		}).insert(ignore_permissions=True)

		result = add_timeline_audio_clip(self.project.name, audio_version.name)
		added = next(clip for clip in result["clips"] if clip["name"] == result["selected_clip"])
		self.assertEqual(added["source_out_frame"], 144)
		self.assertEqual(result["total_frames"], 96)
		self.assertEqual(result["canvas_total_frames"], 144)

	def test_source_audio_can_be_disabled_without_deleting_video(self):
		source_audio = frappe.get_doc({
			"doctype": "Timeline Clip",
			"media_project": self.project.name,
			"shot": self.shot.name,
			"clip_order": 1,
			"track_type": "Audio",
			"track_index": 0,
			"linked_video_clip": self.clip_1.name,
			"timeline_start_frame": 0,
			"enabled": 1,
			"source_asset_version": self.version_1.name,
			"source_in_frame": 0,
			"source_out_frame": 96,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": 96,
			"audio_role": "Source",
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}).insert(ignore_permissions=True)

		set_source_audio_enabled(self.project.name, self.clip_1.name, False)
		source_audio.reload()
		self.clip_1.reload()
		self.assertFalse(source_audio.enabled)
		self.assertTrue(self.clip_1.enabled)

		set_source_audio_enabled(self.project.name, self.clip_1.name, True)
		source_audio.reload()
		self.assertTrue(source_audio.enabled)

	def test_generated_shot_clip_is_disabled_instead_of_deleted(self):
		source_audio = frappe.get_doc({
			"doctype": "Timeline Clip",
			"media_project": self.project.name,
			"shot": self.shot.name,
			"clip_order": 1,
			"track_type": "Audio",
			"track_index": 0,
			"linked_video_clip": self.clip_1.name,
			"timeline_start_frame": 0,
			"enabled": 1,
			"source_asset_version": self.version_1.name,
			"source_in_frame": 0,
			"source_out_frame": 96,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": 96,
			"audio_role": "Source",
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}).insert(ignore_permissions=True)

		delete_timeline_clip(self.project.name, self.clip_1.name)
		self.clip_1.reload()
		source_audio.reload()
		self.assertFalse(self.clip_1.enabled)
		self.assertFalse(source_audio.enabled)
		self.assertTrue(frappe.db.exists("Timeline Clip", self.clip_1.name))

		sync_timeline_source_for_shot(self.shot.name)
		self.assertEqual(
			frappe.db.count("Timeline Clip", {"media_project": self.project.name, "track_type": "Video"}),
			1,
		)

	def test_disabled_source_audio_stays_disabled_when_video_is_split(self):
		source_audio = frappe.get_doc({
			"doctype": "Timeline Clip",
			"media_project": self.project.name,
			"shot": self.shot.name,
			"clip_order": 1,
			"track_type": "Audio",
			"track_index": 0,
			"linked_video_clip": self.clip_1.name,
			"timeline_start_frame": 0,
			"enabled": 0,
			"source_asset_version": self.version_1.name,
			"source_in_frame": 0,
			"source_out_frame": 96,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": 96,
			"audio_role": "Source",
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}).insert(ignore_permissions=True)

		split_timeline_clip(self.project.name, self.clip_1.name, 48)
		source_clips = frappe.get_all(
			"Timeline Clip",
			filters={"media_project": self.project.name, "track_type": "Audio", "audio_role": "Source"},
			fields=["enabled"],
		)
		self.assertEqual(len(source_clips), 2)
		self.assertTrue(all(not clip.enabled for clip in source_clips))

	def test_disabled_source_audio_stays_disabled_after_video_trim(self):
		source_audio = frappe.get_doc({
			"doctype": "Timeline Clip",
			"media_project": self.project.name,
			"shot": self.shot.name,
			"clip_order": 1,
			"track_type": "Audio",
			"track_index": 0,
			"linked_video_clip": self.clip_1.name,
			"timeline_start_frame": 0,
			"enabled": 1,
			"source_asset_version": self.version_1.name,
			"source_in_frame": 0,
			"source_out_frame": 96,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": 96,
			"audio_role": "Source",
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}).insert(ignore_permissions=True)

		set_source_audio_enabled(self.project.name, self.clip_1.name, False)
		with patch(
			"joymedia.services.timeline_editor._get_or_create_source_audio_version",
			return_value=self.version_1.name,
		):
			trim_timeline_clip(self.project.name, self.clip_1.name, 10, 80)
		source_audio.reload()
		self.assertFalse(source_audio.enabled)

	def test_timeline_state_can_be_restored_without_touching_source_assets(self):
		state = {
			"clips": [{
				"name": self.clip_1.name,
				"shot": self.shot.name,
				"clip_order": 1,
				"track_type": "Video",
				"track_index": 0,
				"timeline_start_frame": 0,
				"enabled": 1,
				"source_asset_version": self.version_1.name,
				"source_in_frame": 12,
				"source_out_frame": 84,
				"initial_source_in_frame": 0,
				"initial_source_out_frame": 96,
				"transition_to_next": "Cut",
				"transition_frames": 0,
				"is_outdated": 0,
			}],
		}

		restore_timeline_state(self.project.name, json.dumps(state))
		restored = frappe.get_all(
			"Timeline Clip",
			filters={"media_project": self.project.name},
			fields=["source_asset_version", "source_in_frame", "source_out_frame"],
		)
		self.assertEqual(len(restored), 1)
		self.assertEqual(restored[0].source_asset_version, self.version_1.name)
		self.assertEqual((restored[0].source_in_frame, restored[0].source_out_frame), (12, 84))

	def test_split_and_duplicate_keep_source_asset(self):
		split_timeline_clip(self.project.name, self.clip_1.name, 48)
		clips = frappe.get_all(
			"Timeline Clip", filters={"media_project": self.project.name},
			fields=["name", "source_asset_version", "source_in_frame", "source_out_frame", "clip_order"],
			order_by="clip_order asc",
		)
		self.assertEqual(len(clips), 2)
		self.assertEqual(clips[1].source_asset_version, self.version_1.name)
		self.assertEqual((clips[1].source_in_frame, clips[1].source_out_frame), (48, 96))
		duplicate_timeline_clip(self.project.name, clips[0].name)
		self.assertEqual(frappe.db.count("Timeline Clip", {"media_project": self.project.name}), 3)

	def test_reorder_persists_sequence(self):
		duplicate_timeline_clip(self.project.name, self.clip_1.name)
		clips = frappe.get_all("Timeline Clip", filters={"media_project": self.project.name}, order_by="clip_order asc")
		reorder_timeline_clip(self.project.name, clips[1].name, 1)
		ordered = frappe.get_all(
			"Timeline Clip", filters={"media_project": self.project.name}, fields=["name", "clip_order"],
			order_by="clip_order asc",
		)
		self.assertEqual(ordered[0].name, clips[1].name)

	def test_transition_model_is_intentionally_small(self):
		duplicate_timeline_clip(self.project.name, self.clip_1.name)
		for transition in ("Cut", "Dissolve", "Fade"):
			set_timeline_transition(self.project.name, self.clip_1.name, transition, 12)
			self.clip_1.reload()
			self.assertEqual(self.clip_1.transition_to_next, transition)
		with self.assertRaises(frappe.ValidationError):
			set_timeline_transition(self.project.name, self.clip_1.name, "Wipe Left", 12)

	def test_shot_regeneration_marks_timeline_source_stale_without_replacing_it(self):
		_, version_2 = _create_output_version(self.project, "test-v2.mp4", 3, asset=self.asset)
		self.shot.db_set("selected_output_asset_version", version_2.name, update_modified=False)
		frappe.db.set_value("Media Project", self.project.name, "current_output_asset_version", self.version_1.name)
		sync_timeline_source_for_shot(self.shot.name)
		self.clip_1.reload()
		self.assertEqual(self.clip_1.source_asset_version, self.version_1.name)
		self.assertEqual(self.clip_1.source_out_frame, 96)
		self.assertTrue(self.clip_1.is_outdated)
		update_timeline_source_for_shot(self.project.name, self.shot.name)
		self.clip_1.reload()
		self.assertEqual(self.clip_1.source_asset_version, version_2.name)
		self.assertEqual(self.clip_1.source_out_frame, 72)
		self.assertFalse(self.clip_1.is_outdated)
		self.assertIsNone(frappe.db.get_value("Media Project", self.project.name, "current_output_asset_version"))

	def test_first_generated_shot_creates_timeline_clip_without_full_run(self):
		frappe.delete_doc("Timeline Clip", self.clip_1.name, force=True, ignore_permissions=True)

		sync_timeline_source_for_shot(self.shot.name)

		video_clips = frappe.get_all(
			"Timeline Clip",
			filters={"media_project": self.project.name, "track_type": "Video"},
			fields=["shot", "source_asset_version", "timeline_start_frame"],
		)
		self.assertEqual(len(video_clips), 1)
		self.assertEqual(video_clips[0].shot, self.shot.name)
		self.assertEqual(video_clips[0].source_asset_version, self.version_1.name)
		self.assertEqual(video_clips[0].timeline_start_frame, 0)

	def test_timeline_position_is_persisted_and_movable(self):
		move_timeline_clip(self.project.name, self.clip_1.name, 48, "Video", 1)
		self.clip_1.reload()
		self.assertEqual(self.clip_1.timeline_start_frame, 48)
		from joymedia.services.timeline_editor import get_project_timeline
		clip = get_project_timeline(self.project.name)["clips"][0]
		self.assertEqual(clip["timeline_start_frame"], 48)

	def test_timeline_is_owned_by_the_project(self):
		from joymedia.services.timeline_editor import get_project_timeline
		data = get_project_timeline(self.project.name)
		self.assertEqual(data["project"], self.project.name)
		self.assertEqual(data["media_project"], self.project.name)


def _create_output_version(project, file_name, seconds, asset=None):
	if not asset:
		asset = frappe.get_doc({
			"doctype": "Media Asset",
			"asset_name": "Test Source Video",
			"media_type": "Video",
			"asset_category": "Other",
			"asset_scope": "Project Output",
			"media_project": project.name,
			"status": "Active",
		}).insert(ignore_permissions=True)
	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": file_name,
		"content": _generate_video_bytes(seconds),
		"is_private": 1,
		"attached_to_doctype": "Media Asset",
		"attached_to_name": asset.name,
	}).insert(ignore_permissions=True)
	version = frappe.get_doc({
		"doctype": "Asset Version",
		"media_asset": asset.name,
		"file": file_doc.file_url,
		"source": "Generated",
	}).insert(ignore_permissions=True)
	return asset, version


def _create_workflow():
	return frappe.get_doc({
		"doctype": "Generation Workflow",
		"workflow_key": f"timeline_test_{frappe.generate_hash(length=5)}",
		"adapter_key": "minimax_h3",
		"workflow_json": (
			'{"load_img":{"inputs":{"image":""},"class_type":"VHS_LoadImagePath"},'
			'"minimax_cond":{"inputs":{"length":124},"class_type":"MiniMaxH3ImageToVideo"},'
			'"save_video":{"inputs":{"images":["dec_video",0],"frame_rate":24,'
			'"filename_prefix":"JoyMedia","loop_count":0,"format":"video/h264-mp4",'
			'"pingpong":false,"save_output":true},"class_type":"VHS_VideoCombine"}}'
		),
		"bindings": [{
			"binding_key": "first_frame", "node_key": "load_img", "input_name": "image",
			"required_input_role": "first_frame", "value_type": "File Path", "required": 1,
		}],
	}).insert(ignore_permissions=True).name
