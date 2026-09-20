from unittest.mock import MagicMock, patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from joymedia.services.artifact_service import expire_generation_artifacts, promote_artifact_from_ui


class TestArtifactExpiry(FrappeTestCase):
	@patch("joymedia.services.artifact_service.frappe.db.commit")
	@patch("joymedia.services.artifact_service.frappe.get_doc")
	@patch("joymedia.services.artifact_service.frappe.get_all", return_value=["GART-00001", "GART-00002"])
	def test_expire_generation_artifacts_marks_only_due_temporary_artifacts(
		self, get_all, get_doc, commit
	):
		first_artifact = MagicMock()
		second_artifact = MagicMock()
		first_artifact.frappe_file = None
		second_artifact.frappe_file = None
		get_doc.side_effect = [first_artifact, second_artifact]

		expire_generation_artifacts()

		self.assertEqual(first_artifact.lifecycle_status, "Temporary")
		self.assertEqual(second_artifact.lifecycle_status, "Temporary")
		first_artifact.save.assert_not_called()
		second_artifact.save.assert_not_called()
		get_all.assert_called_once()
		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual(filters["lifecycle_status"], "Temporary")
		self.assertEqual(filters["expires_at"][0], "<")
		commit.assert_called_once()


class TestArtifactPromotion(FrappeTestCase):
	@patch("joymedia.services.artifact_service.frappe.has_permission")
	@patch("joymedia.services.artifact_service.frappe.get_doc")
	def test_quality_review_can_stream_a_temporary_video_artifact(
		self, get_doc, has_permission
	):
		review = frappe._dict(name="QREV-00001", generation_artifact="GART-00001")
		artifact = frappe._dict(
			name="GART-00001",
			lifecycle_status="Temporary",
			media_type="Video",
			frappe_file="/private/files/video.mp4",
		)
		file_doc = frappe._dict(file_name="video.mp4", get_content=lambda: b"video-bytes")
		get_doc.side_effect = [review, artifact, file_doc]

		from joymedia.services.artifact_service import stream_review_artifact

		stream_review_artifact(review.name)

		has_permission.assert_called_once_with("Quality Review", "read", review.name, throw=True)
		self.assertEqual(frappe.local.response.filename, "video.mp4")
		self.assertEqual(frappe.local.response.filecontent, b"video-bytes")
		self.assertEqual(frappe.local.response.content_type, "video/mp4")
		self.assertEqual(frappe.local.response.display_content_as, "inline")
		self.assertEqual(frappe.local.response.type, "download")

	@patch("joymedia.services.artifact_service.frappe.has_permission")
	@patch("joymedia.services.artifact_service.frappe.db.exists", return_value=False)
	@patch("joymedia.services.artifact_service.frappe.get_doc")
	def test_unapproved_artifact_cannot_be_promoted(self, get_doc, exists, has_permission):
		artifact = frappe._dict(
			name="GART-00001",
			lifecycle_status="Temporary",
			media_type="Video",
			frappe_file="/private/files/video.mp4",
		)
		get_doc.return_value = artifact

		with self.assertRaises(ValidationError):
			promote_artifact_from_ui(artifact.name)


	@patch("joymedia.services.artifact_service.frappe.has_permission")
	@patch("joymedia.services.artifact_service.frappe.get_doc")
	def test_promoted_artifact_is_not_downloaded_again(self, get_doc, has_permission):
		artifact = frappe._dict(
			name="GART-00001",
			lifecycle_status="Promoted",
			promoted_asset_version="ASTV-00001",
		)
		get_doc.return_value = artifact

		result = promote_artifact_from_ui(artifact.name)

		self.assertEqual(result, {"asset_version": "ASTV-00001"})
		has_permission.assert_called_once_with("Generation Artifact", "write", artifact.name, throw=True)

	@patch("joymedia.services.artifact_service.frappe.db.commit")
	@patch("joymedia.services.artifact_service.frappe.db.exists", return_value=True)
	@patch("joymedia.services.artifact_service.frappe.db.get_value", return_value=None)
	@patch("joymedia.services.artifact_service.frappe.has_permission")
	@patch("joymedia.services.artifact_service.frappe.get_doc")
	def test_approved_artifact_promotion_persists_video(
		self, get_doc, has_permission, get_value, exists, commit
	):
		artifact = frappe._dict(
			name="GART-00001",
			lifecycle_status="Temporary",
			media_type="Video",
			frappe_file="/private/files/video.mp4",
			generation_attempt="ATT-00001",
		)
		artifact.save = MagicMock()
		attempt = frappe._dict(
			name="ATT-00001",
			status="Completed",
			generation_job="JOB-00001",
			comfyui_endpoint_url="http://worker:8188",
		)
		attempt.save = MagicMock()
		job = frappe._dict(name="JOB-00001", shot_specification="SHOT-00001")
		shot = MagicMock(name="SHOT-00001", media_specification="SPEC-00001")
		media_specification = frappe._dict(name="SPEC-00001", media_project="PROJ-00001")
		media_asset = MagicMock()
		media_asset.name = "AST-00001"
		file_doc = MagicMock()
		file_doc.file_url = "/private/files/video.mp4"
		asset_version = MagicMock()
		asset_version.name = "ASTV-00001"
		def get_document(doctype_or_values, name=None):
			if doctype_or_values == "Generation Artifact":
				return artifact
			if doctype_or_values == "Generation Attempt":
				return attempt
			if doctype_or_values == "Generation Job":
				return job
			if doctype_or_values == "Shot Specification":
				return shot
			if doctype_or_values == "Media Specification":
				return media_specification
			if isinstance(doctype_or_values, dict):
				return {
					"Media Asset": media_asset,
					"File": file_doc,
					"Asset Version": asset_version,
				}[doctype_or_values["doctype"]]
			raise AssertionError(f"Unexpected get_doc call: {doctype_or_values!r}, {name!r}")

		get_doc.side_effect = get_document

		result = promote_artifact_from_ui(artifact.name)

		self.assertEqual(result, {"asset_version": "ASTV-00001"})
		self.assertEqual(artifact.lifecycle_status, "Promoted")
		self.assertEqual(artifact.promoted_asset_version, "ASTV-00001")
		self.assertEqual(attempt.output_asset_version, "ASTV-00001")
		artifact.save.assert_called_once_with(ignore_permissions=True)
		attempt.save.assert_called_once_with(ignore_permissions=True)
		shot.save.assert_not_called()
		commit.assert_called_once()
