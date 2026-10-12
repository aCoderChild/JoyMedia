import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.quality_feedback import _latest_human_reviews


class TestQualityFeedback(FrappeTestCase):
	def test_latest_human_outcome_per_output_supersedes_old_rejection(self):
		reviews = [
			frappe._dict(shot="SHOT-1", output_asset_version="ASTV-1", verdict="Approved"),
			frappe._dict(shot="SHOT-1", output_asset_version="ASTV-1", verdict="Rejected"),
			frappe._dict(shot="SHOT-1", output_asset_version="ASTV-2", verdict="Needs Revision"),
		]

		outcomes = _latest_human_reviews(reviews)

		self.assertEqual(
			[("ASTV-1", "Approved"), ("ASTV-2", "Needs Revision")],
			[(row.output_asset_version, row.verdict) for row in outcomes],
		)
