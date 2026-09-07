# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from .generation_artifact import GenerationArtifact


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class TestGenerationArtifact(FrappeTestCase):
	def test_promoted_artifact_requires_promoted_asset_version(self):
		artifact = frappe._dict(lifecycle_status="Promoted", promoted_asset_version=None)
		artifact.is_new = lambda: True

		with self.assertRaises(ValidationError):
			GenerationArtifact.validate(artifact)

	@patch(
		"joymedia.joymedia.doctype.generation_artifact.generation_artifact.frappe.db.get_value"
	)
	def test_existing_artifact_identity_cannot_change(self, get_value):
		artifact = frappe._dict(
			name="GART-00001",
			lifecycle_status="Temporary",
			artifact_key="ATT-00001:primary_video",
			generation_attempt="ATT-00002",
			remote_filename="video.mp4",
			remote_subfolder="",
			remote_file_type="output",
		)
		artifact.is_new = lambda: False
		get_value.return_value = frappe._dict(
			lifecycle_status="Temporary",
			artifact_key="ATT-00001:primary_video",
			generation_attempt="ATT-00001",
			remote_filename="video.mp4",
			remote_subfolder="",
			remote_file_type="output",
		)

		with self.assertRaises(ValidationError):
			GenerationArtifact.validate(artifact)

	@patch(
		"joymedia.joymedia.doctype.generation_artifact.generation_artifact.frappe.db.get_value"
	)
	def test_deleted_artifact_cannot_leave_deleted_state(self, get_value):
		artifact = frappe._dict(
			name="GART-00001",
			lifecycle_status="Temporary",
			artifact_key="ATT-00001:primary_video",
			generation_attempt="ATT-00001",
			remote_filename="video.mp4",
			remote_subfolder="",
			remote_file_type="output",
		)
		artifact.is_new = lambda: False
		get_value.return_value = frappe._dict(
			lifecycle_status="Deleted",
			artifact_key="ATT-00001:primary_video",
			generation_attempt="ATT-00001",
			remote_filename="video.mp4",
			remote_subfolder="",
			remote_file_type="output",
		)

		with self.assertRaises(ValidationError):
			GenerationArtifact.validate(artifact)
