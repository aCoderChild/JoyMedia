from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from . import result_ingestor


class IntegrationTestResultIngestor(IntegrationTestCase):
	def test_sync_active_attempts_polls_external_attempts(self):
		with (
			patch.object(
				result_ingestor.frappe,
				"get_all",
				return_value=[
					frappe._dict(name="ATT-EXTERNAL", external_job_id="comfy-1"),
					frappe._dict(name="ATT-NO-ID", external_job_id=None),
				],
			) as get_all,
			patch.object(
				result_ingestor,
				"sync_attempt_result",
				return_value={"status": "Completed", "output_asset_version": "ASTV-00001"},
			) as sync_attempt_result,
			patch.object(result_ingestor.frappe.db, "commit") as commit,
		):
			result = result_ingestor.sync_active_attempts()

		get_all.assert_called_once_with(
			"Generation Attempt",
			filters={"status": ["in", ["Queued", "Running"]]},
			fields=["name", "external_job_id"],
		)
		sync_attempt_result.assert_called_once_with("ATT-EXTERNAL")
		commit.assert_called_once()
		self.assertEqual(
			result,
			[
				{
					"attempt": "ATT-EXTERNAL",
					"status": "Completed",
					"output_asset_version": "ASTV-00001",
				}
			],
		)
