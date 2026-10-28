from unittest import TestCase
from unittest.mock import patch

from joymedia.services.generation.creative_batch import _defer_reference_analysis, _next_prepare_index
from joymedia.services.planning.creative import ReferenceAnalysisUnavailable


class TestReferenceAnalysisRetry(TestCase):
	def test_failure_waits_then_retries_same_video_with_a_limit(self):
		variant = {"status": "Planning", "nonce": "original", "project": "existing"}
		with (
			patch("joymedia.services.generation.creative_batch.time.time", return_value=1000),
			patch("joymedia.services.generation.creative_batch._active_variant_limit", return_value=2),
		):
			self.assertTrue(
				_defer_reference_analysis(variant, ReferenceAnalysisUnavailable("analysis failed"))
			)
			self.assertEqual(variant["retry_after"], 1060)
			self.assertIsNone(_next_prepare_index([variant]))
		with (
			patch("joymedia.services.generation.creative_batch.time.time", return_value=1061),
			patch("joymedia.services.generation.creative_batch._active_variant_limit", return_value=2),
		):
			self.assertEqual(_next_prepare_index([variant]), 0)
			self.assertTrue(
				_defer_reference_analysis(variant, ReferenceAnalysisUnavailable("analysis failed"))
			)
			self.assertFalse(
				_defer_reference_analysis(variant, ReferenceAnalysisUnavailable("analysis failed"))
			)
		self.assertEqual((variant["project"], variant["nonce"]), ("existing", "original"))
		self.assertFalse(_defer_reference_analysis({}, ValueError("invalid input")))
