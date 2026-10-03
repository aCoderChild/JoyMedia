from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.joymedia.doctype.timeline_clip.timeline_clip import (
	_restore_pristine_generated_shot_order,
)


class TestGeneratedTimelineOrdering(TestCase):
	def test_pristine_generated_clips_follow_storyboard_order(self):
		clips = [
			frappe._dict(
				name="TLCLIP-SHOT-2",
				shot="SHOT-2",
				clip_order=1,
				timeline_start_frame=0,
				initial_timeline_start_frame=0,
				source_in_frame=0,
				source_out_frame=120,
				initial_source_in_frame=0,
				initial_source_out_frame=120,
				transition_to_next="Cut",
				transition_frames=0,
				is_outdated=0,
			),
			frappe._dict(
				name="TLCLIP-SHOT-1",
				shot="SHOT-1",
				clip_order=2,
				timeline_start_frame=120,
				initial_timeline_start_frame=120,
				source_in_frame=0,
				source_out_frame=96,
				initial_source_in_frame=0,
				initial_source_out_frame=96,
				transition_to_next="Cut",
				transition_frames=0,
				is_outdated=0,
			),
		]
		shots = [
			frappe._dict(name="SHOT-1", shot_number=1),
			frappe._dict(name="SHOT-2", shot_number=2),
		]

		with (
			patch(
				"joymedia.joymedia.doctype.timeline_clip.timeline_clip.frappe.get_all",
				side_effect=[clips, shots],
			),
			patch(
				"joymedia.joymedia.doctype.timeline_clip.timeline_clip.frappe.db.get_value",
				return_value=None,
			),
			patch(
				"joymedia.joymedia.doctype.timeline_clip.timeline_clip.frappe.db.set_value"
			) as set_value,
		):
			_restore_pristine_generated_shot_order("PRJ-00001")

		updates = {
			call.args[1]: call.args[2]
			for call in set_value.call_args_list
			if call.args[0] == "Timeline Clip"
		}
		self.assertEqual(updates["TLCLIP-SHOT-1"]["clip_order"], 1)
		self.assertEqual(updates["TLCLIP-SHOT-1"]["timeline_start_frame"], 0)
		self.assertEqual(updates["TLCLIP-SHOT-2"]["clip_order"], 2)
		self.assertEqual(updates["TLCLIP-SHOT-2"]["timeline_start_frame"], 96)

	def test_editor_move_disables_automatic_storyboard_reordering(self):
		clips = [
			frappe._dict(
				name="TLCLIP-SHOT-2",
				shot="SHOT-2",
				clip_order=1,
				timeline_start_frame=24,
				initial_timeline_start_frame=0,
				source_in_frame=0,
				source_out_frame=120,
				initial_source_in_frame=0,
				initial_source_out_frame=120,
				transition_to_next="Cut",
				transition_frames=0,
				is_outdated=0,
			),
		]

		with (
			patch(
				"joymedia.joymedia.doctype.timeline_clip.timeline_clip.frappe.get_all",
				return_value=clips,
			),
			patch(
				"joymedia.joymedia.doctype.timeline_clip.timeline_clip.frappe.db.set_value"
			) as set_value,
		):
			_restore_pristine_generated_shot_order("PRJ-00001")

		set_value.assert_not_called()
