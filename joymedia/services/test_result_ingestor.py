from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from . import result_ingestor


class IntegrationTestResultIngestor(IntegrationTestCase):
	@patch("joymedia.services.result_ingestor.download_output", return_value=b"video-bytes")
	@patch("joymedia.services.result_ingestor.frappe.get_doc")
	def test_completed_artifact_is_copied_to_a_private_frappe_file(self, get_doc, download_output):
		artifact = frappe._dict(
			name="GART-00001",
			frappe_file=None,
			remote_filename="JOB-00001_ATT-00001.mp4",
			remote_subfolder="",
			remote_file_type="output",
		)
		artifact.save = MagicMock()
		attempt = frappe._dict(comfyui_endpoint_url="http://worker:8188")
		file_doc = frappe._dict(file_url="/private/files/JOB-00001_ATT-00001.mp4")
		file_doc.insert = MagicMock()
		get_doc.return_value = file_doc

		result_ingestor._store_artifact_file_in_frappe(artifact, attempt)

		download_output.assert_called_once_with(
			"JOB-00001_ATT-00001.mp4", "", "output", base_url="http://worker:8188"
		)
		self.assertEqual(artifact.storage_backend, "Frappe File")
		self.assertEqual(artifact.frappe_file, "/private/files/JOB-00001_ATT-00001.mp4")
		self.assertEqual(artifact.storage_uri, artifact.frappe_file)
		self.assertEqual(artifact.mime_type, "video/mp4")
		self.assertEqual(artifact.size_bytes, len(b"video-bytes"))
		file_doc.insert.assert_called_once_with(ignore_permissions=True)
		artifact.save.assert_called_once_with(ignore_permissions=True)

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
				return_value={"status": "Completed", "output_artifact": "GART-00001"},
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
					"output_artifact": "GART-00001",
				}
			],
		)
