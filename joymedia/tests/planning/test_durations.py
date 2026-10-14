from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning.durations import ensure_shot_planning_editable, recalculate_shot_durations


class TestShotDurationPlanner(FrappeTestCase):
	@patch("joymedia.services.planning.durations.frappe.db.exists", return_value="RUN-00001")
	def test_active_generation_blocks_shot_planning_edits(self, exists):
		with self.assertRaises(frappe.ValidationError):
			ensure_shot_planning_editable("PROJ-00001")
		exists.assert_called_once_with(
			"Generation Run",
			{"media_project": "PROJ-00001", "status": ["in", ["Queued", "Running"]]},
		)

	@patch("joymedia.services.planning.durations.frappe.db.set_value")
	@patch("joymedia.services.planning.durations.frappe.get_all")
	@patch("joymedia.services.planning.durations.frappe.get_doc")
	def test_divisible_duration_is_distributed_in_whole_frames(self, get_doc, get_all, set_value):
		get_doc.return_value = _specification(total_duration_seconds=31, output_fps=24)
		get_all.return_value = [_shot(index) for index in range(1, 7)]

		result = recalculate_shot_durations("SPEC-00001")

		self.assertEqual({"total_frames": 744, "shots": 6}, result)
		self.assertEqual(6, set_value.call_count)
		for call in set_value.call_args_list:
			self.assertEqual(124, call.args[2]["planned_frame_count"])
			self.assertEqual(124 / 24, call.args[2]["duration_seconds"])
			self.assertFalse(call.kwargs["update_modified"])

	@patch("joymedia.services.planning.durations.frappe.db.set_value")
	@patch("joymedia.services.planning.durations.frappe.get_all")
	@patch("joymedia.services.planning.durations.frappe.get_doc")
	def test_remainder_frames_are_assigned_to_earliest_shots(self, get_doc, get_all, set_value):
		get_doc.return_value = _specification(total_duration_seconds=30, output_fps=24)
		get_all.return_value = [_shot(index) for index in range(1, 8)]

		recalculate_shot_durations("SPEC-00001")

		self.assertEqual(
			[103, 103, 103, 103, 103, 103, 102],
			[call.args[2]["planned_frame_count"] for call in set_value.call_args_list],
		)

	@patch("joymedia.services.planning.durations.frappe.db.set_value")
	@patch("joymedia.services.planning.durations.frappe.get_all")
	@patch("joymedia.services.planning.durations.frappe.get_doc")
	def test_single_shot_receives_the_full_timeline(self, get_doc, get_all, set_value):
		get_doc.return_value = _specification(total_duration_seconds=8, output_fps=24)
		get_all.return_value = [_shot(1)]

		recalculate_shot_durations("SPEC-00001")

		self.assertEqual(192, set_value.call_args.args[2]["planned_frame_count"])
		self.assertEqual(8, set_value.call_args.args[2]["duration_seconds"])

	@patch("joymedia.services.planning.durations.frappe.db.set_value")
	@patch("joymedia.services.planning.durations.frappe.get_all")
	@patch("joymedia.services.planning.durations.frappe.get_doc")
	def test_image_workflow_uses_video_safe_timeline_fps(self, get_doc, get_all, set_value):
		get_doc.return_value = _specification(total_duration_seconds=10, output_fps=0)
		get_all.return_value = [_shot(1), _shot(2)]

		result = recalculate_shot_durations("SPEC-00001")

		self.assertEqual({"total_frames": 240, "shots": 2}, result)
		self.assertEqual([120, 120], [call.args[2]["planned_frame_count"] for call in set_value.call_args_list])

	@patch("joymedia.services.planning.durations.frappe.db.set_value")
	@patch("joymedia.services.planning.durations.frappe.get_all")
	@patch("joymedia.services.planning.durations.frappe.get_doc")
	def test_source_timed_shots_keep_authored_durations(self, get_doc, get_all, set_value):
		get_doc.return_value = _specification(total_duration_seconds=30, output_fps=24)
		get_all.return_value = [
			frappe._dict(
				name="SHOT-00001", shot_number=1, duration_seconds=4,
				source_timing="0:00 - 0:04", source_start_seconds=0, source_end_seconds=4,
			),
			frappe._dict(
				name="SHOT-00002", shot_number=2, duration_seconds=8,
				source_timing="0:07 - 0:15", source_start_seconds=7, source_end_seconds=15,
			),
		]

		result = recalculate_shot_durations("SPEC-00001")

		self.assertEqual({"total_frames": 288, "shots": 2, "preserved_source_timing": True}, result)
		self.assertEqual([96, 192], [call.args[2]["planned_frame_count"] for call in set_value.call_args_list])
		self.assertTrue(all("duration_seconds" not in call.args[2] for call in set_value.call_args_list))


def _specification(**values):
	return type(
		"Specification",
		(),
		{
			"name": "SPEC-00001",
			"workflow": "WF-00001",
			"output_fps": 24,
			**values,
		},
	)()


def _shot(number):
	return frappe._dict(name=f"SHOT-{number:05d}", shot_number=number)
