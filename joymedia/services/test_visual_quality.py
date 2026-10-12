from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from joymedia.services.visual_quality import normalize_visual_qa, queue_automated_shot_review


class TestVisualQuality(FrappeTestCase):
	def test_visual_qa_requires_all_scores_to_pass(self):
		result = normalize_visual_qa({
			"reference_fidelity": 92, "temporal_consistency": 74,
			"prompt_adherence": 98, "shot_continuity": 89, "verdict": "Approved",
		})
		self.assertEqual("Needs Revision", result["verdict"])
		self.assertEqual(74, result["scores"]["temporal_consistency"])


	def test_visual_qa_normalizes_valid_approval(self):
		result = normalize_visual_qa({
			"reference_fidelity": 81, "temporal_consistency": "80",
			"prompt_adherence": 79.6, "shot_continuity": 77, "verdict": "Approved",
		})
		self.assertEqual("Approved", result["verdict"])
		self.assertEqual(80, result["scores"]["prompt_adherence"])

	@patch("joymedia.services.visual_quality.enqueue_render")
	@patch("joymedia.services.visual_quality._already_reviewed", return_value=False)
	@patch("joymedia.services.visual_quality.is_configured", return_value=True)
	def test_visual_qa_is_queued_not_run_inline(self, configured, reviewed, enqueue):
		self.assertTrue(queue_automated_shot_review("SHOT-1", "ASTV-1"))
		enqueue.assert_called_once()
		self.assertEqual("joymedia.services.visual_quality.run_automated_shot_review", enqueue.call_args.args[0])
