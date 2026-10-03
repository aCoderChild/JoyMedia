import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.timeline_editor import (
	duplicate_timeline_clip,
	fit_audio_clip_to_video,
	reorder_timeline_clip,
	set_timeline_transition,
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
