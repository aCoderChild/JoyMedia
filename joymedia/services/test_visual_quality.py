from frappe.tests.utils import FrappeTestCase

from joymedia.services.visual_quality import normalize_visual_qa


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
