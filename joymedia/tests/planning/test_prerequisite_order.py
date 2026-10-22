from unittest import TestCase
from unittest.mock import patch

from joymedia.services.planning.script_review import _cross_check_missing_actions


class TestPrerequisiteOrder(TestCase):
	def test_reviewer_can_ground_a_narration_action_contradiction(self):
		from joymedia.services.planning.script_review import review_script_actions

		script = {"scenes": [{"action": "Hold the unopened pack.", "voice_over": "Watch the sheet absorb the spill.", "on_screen_text": "Absorption demonstrated"}]}
		review = {"coverage": [{"scene": 1, "action_quote": "Hold the unopened pack."}], "issues": [{"scene": 1, "category": "brief_contradiction", "quote": "Watch the sheet absorb the spill.", "instruction": "Match narration to the visible handling action."}]}
		with patch("joymedia.services.planning.production._ask_planner", return_value=review) as planner:
			self.assertEqual(review, review_script_actions(script))
			self.assertIn(script["scenes"][0]["voice_over"], planner.call_args.args[0])
			self.assertIn(script["scenes"][0]["on_screen_text"], planner.call_args.args[0])

	def test_later_acquisition_cannot_retract_earlier_use_defect(self):
		for actions, scene, expected in (
			(["Press the sheet on water.", "Extract a sheet."], 1, "missing_prerequisite"),
			(["Extract a sheet.", "Press the sheet on water."], 2, "production_detail"),
			(["Extract a sheet. Press the sheet on water."], 1, "production_detail"),
			(["Press the sheet on water. Extract a sheet."], 1, "missing_prerequisite"),
		):
			finding = {"scene": scene, "category": "missing_prerequisite", "quote": "Press the sheet on water.", "instruction": "Acquire the sheet before use."}
			with self.subTest(actions=actions), patch(
				"joymedia.services.planning.production._ask_planner", return_value={"already_written": "Extract a sheet."}
			):
				result = _cross_check_missing_actions({"issues": [finding]}, {"scenes": [{"action": a} for a in actions]})
				self.assertEqual(expected, result["issues"][0]["category"])
