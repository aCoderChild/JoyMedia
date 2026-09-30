from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

class TestArtifactService(FrappeTestCase):
	@patch("joymedia.services.artifact_service.frappe.has_permission")
	@patch("joymedia.services.artifact_service.frappe.get_doc")
	def test_generation_artifact_can_stream_a_temporary_video_artifact(
		self, get_doc, has_permission
	):
		artifact = frappe._dict(name="GART-00001", media_type="Video", frappe_file="/private/files/video.mp4")
		file_doc = frappe._dict(file_name="video.mp4", get_content=lambda: b"video-bytes")
		get_doc.side_effect = [artifact, file_doc]

		from joymedia.services.artifact_service import stream_artifact

		stream_artifact(artifact.name)

		has_permission.assert_called_once_with("Generation Artifact", "read", artifact.name, throw=True)
		self.assertEqual(frappe.local.response.filename, "video.mp4")
		self.assertEqual(frappe.local.response.filecontent, b"video-bytes")
		self.assertEqual(frappe.local.response.content_type, "video/mp4")
		self.assertEqual(frappe.local.response.display_content_as, "inline")
		self.assertEqual(frappe.local.response.type, "download")
