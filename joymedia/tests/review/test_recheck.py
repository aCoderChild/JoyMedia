import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from joymedia.services.review.admission import digest
from joymedia.services.review.recheck import checked_recheck, queue_held_evidence_recheck


class TestHeldEvidenceRecheck(TestCase):
	def test_only_unchanged_current_evidence_can_supplement_an_unknown_failure(self):
		for defect in (None, "attempt", "bytes", "policy", "original", "violation", "cancelled"):
			with self.subTest(defect=defect), TemporaryDirectory() as directory:
				original = None if defect == "cancelled" else {"status": "Not Checked", "results": []}
				if defect == "violation":
					original["results"] = [{"verdict": "violated"}]
				report = {
					"stage": "explicit_recheck",
					"attempt": "A",
					"original_admission_sha256": digest(json.dumps(original, sort_keys=True).encode()),
					"policy": {"implementation_sha256": "old" if defect == "policy" else "current"},
				}
				payload = json.dumps(report).encode()
				path = Path(directory) / "evidence.json"
				path.write_bytes(payload)
				record = SimpleNamespace(
					generation_attempt="OTHER" if defect == "attempt" else "A",
					artifact_key="A:visual_recheck:unique",
					frappe_file="file",
					provider_locator="changed" if defect == "bytes" else digest(payload),
				)
				if defect == "original":
					original["error"] = "A different original report"
				with (
					patch(
						"frappe.get_doc", side_effect=[record, SimpleNamespace(get_full_path=lambda: path)]
					),
					patch("joymedia.services.review.admission.implementation_hash", return_value="current"),
				):
					if defect and defect != "cancelled":
						with self.assertRaises(ValueError):
							checked_recheck("REVIEW", "A", original)
					else:
						self.assertEqual(report, checked_recheck("REVIEW", "A", original))
				# Independent evidence does not rewrite the original failed admission.
				self.assertTrue(original is None or original["status"] == "Not Checked")

	def test_a_rejected_source_cannot_enqueue_a_review(self):
		with (
			patch("joymedia.services.review.recheck._source", side_effect=ValueError("Witnessed violation")),
			patch("frappe.enqueue") as enqueue,
		):
			with self.assertRaises(ValueError):
				queue_held_evidence_recheck("P", "S", "A", "hash")
			enqueue.assert_not_called()
