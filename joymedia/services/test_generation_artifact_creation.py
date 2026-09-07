from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.result_ingestor import _create_primary_artifact


class TestGenerationArtifactCreation(FrappeTestCase):
	@patch("joymedia.services.result_ingestor.now_datetime", return_value=datetime(2026, 9, 7, 12, 0))
	@patch("joymedia.services.result_ingestor.add_to_date", return_value=datetime(2026, 9, 10, 12, 0))
	@patch("joymedia.services.result_ingestor.frappe.get_doc")
	@patch("joymedia.services.result_ingestor.frappe.db.get_value", return_value=None)
	def test_primary_artifact_records_remote_output_without_download(
		self, get_value, get_doc, add_to_date, now_datetime
	):
		artifact = MagicMock()
		get_doc.return_value = artifact
		attempt = frappe._dict(name="ATT-00001")
		output = {"filename": "video.mp4", "subfolder": "joymedia", "type": "output"}

		result = _create_primary_artifact(attempt, output)

		self.assertIs(result, artifact)
		get_value.assert_called_once_with(
			"Generation Artifact", {"artifact_key": "ATT-00001:primary_video"}, "name"
		)
		get_doc.assert_called_once_with(
			{
				"doctype": "Generation Artifact",
				"artifact_key": "ATT-00001:primary_video",
				"generation_attempt": "ATT-00001",
				"artifact_role": "Primary Video",
				"media_type": "Video",
				"storage_backend": "ComfyUI",
				"remote_filename": "video.mp4",
				"remote_subfolder": "joymedia",
				"remote_file_type": "output",
				"lifecycle_status": "Temporary",
				"expires_at": datetime(2026, 9, 10, 12, 0),
			}
		)
		artifact.insert.assert_called_once_with(ignore_permissions=True)

	@patch("joymedia.services.result_ingestor.frappe.get_doc")
	@patch("joymedia.services.result_ingestor.frappe.db.get_value", return_value="GART-00001")
	def test_primary_artifact_is_idempotent(self, get_value, get_doc):
		artifact = MagicMock()
		get_doc.return_value = artifact

		result = _create_primary_artifact(frappe._dict(name="ATT-00001"), {"filename": "video.mp4"})

		self.assertIs(result, artifact)
		get_doc.assert_called_once_with("Generation Artifact", "GART-00001")
		artifact.insert.assert_not_called()
