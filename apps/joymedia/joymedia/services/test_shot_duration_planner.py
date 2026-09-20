from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from .shot_duration_planner import recalculate_shot_durations


class TestShotDurationPlanner(FrappeTestCase):
	@patch("joymedia.services.shot_duration_planner.frappe.db.set_value")
	@patch("joymedia.services.shot_duration_planner.frappe.get_all")
	@patch("joymedia.services.shot_duration_planner.frappe.get_doc")
	def test_divisible_duration_is_distributed_in_whole_frames(self, get_doc, get_all, set_value):
		get_doc.return_value = _specification(total_duration_seconds=31, target_fps=24)
		get_all.return_value = [_shot(index) for index in range(1, 7)]

		result = recalculate_shot_durations("SPEC-00001")

		self.assertEqual({"total_frames": 744, "shots": 6}, result)
		self.assertEqual(6, set_value.call_count)
		for call in set_value.call_args_list:
			self.assertEqual(124, call.args[2]["planned_frame_count"])
			self.assertEqual(124 / 24, call.args[2]["duration_seconds"])
			self.assertFalse(call.kwargs["update_modified"])

	@patch("joymedia.services.shot_duration_planner.frappe.db.set_value")
	@patch("joymedia.services.shot_duration_planner.frappe.get_all")
	@patch("joymedia.services.shot_duration_planner.frappe.get_doc")
	def test_remainder_frames_are_assigned_to_earliest_shots(self, get_doc, get_all, set_value):
		get_doc.return_value = _specification(total_duration_seconds=30, target_fps=24)
		get_all.return_value = [_shot(index) for index in range(1, 8)]

		recalculate_shot_durations("SPEC-00001")

		self.assertEqual(
			[103, 103, 103, 103, 103, 103, 102],
			[call.args[2]["planned_frame_count"] for call in set_value.call_args_list],
		)

	@patch("joymedia.services.shot_duration_planner.frappe.db.set_value")
	@patch("joymedia.services.shot_duration_planner.frappe.get_all")
	@patch("joymedia.services.shot_duration_planner.frappe.get_doc")
	def test_single_shot_receives_the_full_timeline(self, get_doc, get_all, set_value):
		get_doc.return_value = _specification(total_duration_seconds=8, target_fps=24)
		get_all.return_value = [_shot(1)]

		recalculate_shot_durations("SPEC-00001")

		self.assertEqual(192, set_value.call_args.args[2]["planned_frame_count"])
		self.assertEqual(8, set_value.call_args.args[2]["duration_seconds"])


def _specification(**values):
	return type("Specification", (), {"name": "SPEC-00001", **values})()


def _shot(number):
	return frappe._dict(name=f"SHOT-{number:05d}", shot_number=number)
