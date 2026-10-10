from frappe.tests.utils import FrappeTestCase

from joymedia.joymedia.report.analytics import _is_selected_output, _review_outcome


class TestAttemptAnalytics(FrappeTestCase):
	def test_selected_output_uses_asset_version_lineage(self):
		selected_outputs_by_shot = {"SHOT-00001": "ASTV-00042"}
		source_attempt_by_output = {"ASTV-00042": "ATT-00007"}

		self.assertTrue(
			_is_selected_output(
				"ATT-00007", "SHOT-00001", selected_outputs_by_shot, source_attempt_by_output
			)
		)
		self.assertFalse(
			_is_selected_output(
				"ATT-00006", "SHOT-00001", selected_outputs_by_shot, source_attempt_by_output
			)
		)

	def test_selected_output_rejects_an_unrelated_asset_version(self):
		self.assertFalse(
			_is_selected_output(
				"ATT-00007",
				"SHOT-00001",
				{"SHOT-00001": "ASTV-00042"},
				{"ASTV-00042": "ATT-00008"},
			)
		)

	def test_review_outcome_prefers_human_verdict_over_selection_proxy(self):
		self.assertEqual((False, True), _review_outcome("Rejected", True))
		self.assertEqual((True, True), _review_outcome("Approved", False))
		self.assertEqual((True, True), _review_outcome(None, True))
		self.assertEqual((False, False), _review_outcome(None, False))
