from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.result_ingestor import _create_primary_artifact


class TestGenerationArtifactCreation(FrappeTestCase):
	@patch("joymedia.services.result_ingestor.frappe.get_doc")
	@patch("joymedia.services.result_ingestor.frappe.db.get_value", return_value=None)
	def test_primary_artifact_starts_as_temporary_frappe_file_artifact(
		self, get_value, get_doc
	):
		artifact = MagicMock()
		get_doc.return_value = artifact
		attempt = frappe._dict(name="ATT-00001")
		result = _create_primary_artifact(attempt)

		self.assertIs(result, artifact)
		get_value.assert_called_once_with(
			"Generation Artifact",
			{"generation_attempt": "ATT-00001", "artifact_role": "Primary Video"},
			"name",
		)
		get_doc.assert_called_once_with(
			{
				"doctype": "Generation Artifact",
				"artifact_key": "ATT-00001:primary_video",
				"artifact_role": "Primary Video",
				"generation_attempt": "ATT-00001",
				"media_type": "Video",
				"lifecycle_status": "Temporary",
			}
		)
		artifact.insert.assert_called_once_with(ignore_permissions=True)

	@patch("joymedia.services.result_ingestor.frappe.get_doc")
	@patch("joymedia.services.result_ingestor.frappe.db.get_value", return_value="GART-00001")
	def test_primary_artifact_is_idempotent(self, get_value, get_doc):
		artifact = MagicMock()
		get_doc.return_value = artifact

		result = _create_primary_artifact(frappe._dict(name="ATT-00001"))

		self.assertIs(result, artifact)
		get_doc.assert_called_once_with("Generation Artifact", "GART-00001")
		artifact.insert.assert_not_called()
