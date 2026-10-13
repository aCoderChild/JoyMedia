from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.audio_plan import build_audio_plan, parse_audio_cues, place_cue_audio
from joymedia.services.test_timeline_editor import _create_output_version, _create_workflow, _generate_audio_bytes


class TestAudioCueParsing(FrappeTestCase):
	def test_labelled_lines_become_cues_and_unlabelled_text_is_ignored(self):
		text = "SFX: Tiếng cốc đổ + giấy lau\nBGM: Dồn dập, kịch tính\nGhi chú không nhãn"
		self.assertEqual([("SFX", "Tiếng cốc đổ + giấy lau"), ("BGM", "Dồn dập, kịch tính")], parse_audio_cues(text))

	def test_empty_cues_yield_nothing(self):
		self.assertEqual([], parse_audio_cues(""))
		self.assertEqual([], parse_audio_cues(None))


class TestAudioPlan(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc({
			"doctype": "Media Project", "project_name": "Audio Plan", "workflow": _create_workflow(),
			"total_duration_seconds": 2, "delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)
		self.shot = frappe.get_doc({
			"doctype": "Shot", "media_project": self.project.name, "shot_number": 1, "generation_prompt": "A scene.",
			"duration_seconds": 2.0, "voice_over": '"Xin chào"', "audio_cues": "SFX: pop",
		}).insert(ignore_permissions=True)
		_asset, video = _create_output_version(self.project, "scene.mp4", 2)
		frappe.get_doc({
			"doctype": "Timeline Clip", "media_project": self.project.name, "shot": self.shot.name, "clip_order": 1,
			"track_type": "Video", "track_index": 0, "timeline_start_frame": 48, "initial_timeline_start_frame": 48,
			"enabled": 1, "source_asset_version": video.name, "source_in_frame": 0, "source_out_frame": 48,
			"initial_source_in_frame": 0, "initial_source_out_frame": 48,
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _audio_version(self):
		asset = frappe.get_doc({
			"doctype": "Media Asset", "asset_name": "VO", "media_type": "Audio", "asset_category": "Audio",
			"asset_scope": "Project Output", "media_project": self.project.name, "status": "Active",
		}).insert(ignore_permissions=True)
		file_doc = frappe.get_doc({
			"doctype": "File", "file_name": "vo.flac", "content": _generate_audio_bytes(), "is_private": 1,
			"attached_to_doctype": "Media Asset", "attached_to_name": asset.name,
		}).insert(ignore_permissions=True)
		return frappe.get_doc({
			"doctype": "Asset Version", "media_asset": asset.name, "file": file_doc.file_url, "source": "Uploaded",
		}).insert(ignore_permissions=True)

	def test_cues_start_unscheduled_at_their_shot_position(self):
		plan = build_audio_plan(self.project.name)
		self.assertEqual([("Voiceover", 48, False), ("SFX", 48, False)], [(c["role"], c["start_frame"], c["scheduled"]) for c in plan])

	def test_placing_audio_schedules_the_cue_and_ducks_for_narration(self):
		version = self._audio_version()
		result = place_cue_audio(self.project.name, self.shot.name, "Voiceover", version.name)

		self.assertEqual(48, result["start_frame"])
		self.assertEqual(1, frappe.db.get_value("Timeline Clip", result["clip"], "duck_others"))
		plan = {c["role"]: c for c in build_audio_plan(self.project.name)}
		self.assertTrue(plan["Voiceover"]["scheduled"])
		self.assertFalse(plan["SFX"]["scheduled"])

	def test_unknown_role_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			place_cue_audio(self.project.name, self.shot.name, "Laugh", "AV")


class TestCloseTimelineGaps(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc({
			"doctype": "Media Project", "project_name": "Close Gaps", "workflow": _create_workflow(),
			"total_duration_seconds": 10, "delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)
		self.clips = []
		for number, start in ((1, 0), (2, 96)):
			shot = frappe.get_doc({
				"doctype": "Shot", "media_project": self.project.name, "shot_number": number,
				"generation_prompt": "A scene.", "duration_seconds": 2.0,
			}).insert(ignore_permissions=True)
			_asset, video = _create_output_version(self.project, f"s{number}.mp4", 2)
			self.clips.append(frappe.get_doc({
				"doctype": "Timeline Clip", "media_project": self.project.name, "shot": shot.name, "clip_order": number,
				"track_type": "Video", "track_index": 0, "timeline_start_frame": start,
				"initial_timeline_start_frame": start, "enabled": 1, "source_asset_version": video.name,
				"source_in_frame": 0, "source_out_frame": 48, "initial_source_in_frame": 0, "initial_source_out_frame": 48,
			}).insert(ignore_permissions=True))
		self.second_shot = self.clips[1].shot

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_scenes_cut_directly_and_narration_moves_with_its_scene(self):
		from joymedia.services.timeline_editor import close_timeline_gaps

		version = TestAudioPlan._audio_version(self)
		narration = place_cue_audio(self.project.name, self.second_shot, "Voiceover", version.name)["clip"]
		self.assertEqual(96, frappe.db.get_value("Timeline Clip", narration, "timeline_start_frame"))

		close_timeline_gaps(self.project.name)

		self.assertEqual([0, 48], [frappe.db.get_value("Timeline Clip", c.name, "timeline_start_frame") for c in self.clips])
		self.assertEqual(48, frappe.db.get_value("Timeline Clip", narration, "timeline_start_frame"))
		self.assertEqual(4, frappe.db.get_value("Media Project", self.project.name, "total_duration_seconds"))


class TestGenerateCueAudioGuards(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc({
			"doctype": "Media Project", "project_name": "Gen Audio", "workflow": _create_workflow(),
			"total_duration_seconds": 2, "delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)
		self.shot = frappe.get_doc({
			"doctype": "Shot", "media_project": self.project.name, "shot_number": 1, "generation_prompt": "A scene.",
			"duration_seconds": 2.0, "audio_cues": "SFX: pop",
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_narration_cannot_be_generated_from_video(self):
		from joymedia.services.audio_plan import generate_cue_audio

		with self.assertRaises(frappe.ValidationError):
			generate_cue_audio(self.project.name, self.shot.name, "Voiceover")

	def test_an_unrendered_scene_has_nothing_to_listen_to(self):
		from joymedia.services.audio_plan import generate_cue_audio

		with self.assertRaises(frappe.ValidationError):
			generate_cue_audio(self.project.name, self.shot.name, "SFX")
