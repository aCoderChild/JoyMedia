# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from .media_project import MediaProject


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestMediaProject(IntegrationTestCase):
	"""
	Integration tests for MediaProject.
	Use this class for testing interactions between multiple components.
	"""

	@patch("joymedia.joymedia.doctype.media_project.media_project.frappe.db.commit")
	@patch("joymedia.joymedia.doctype.media_project.media_project.frappe.db.set_value")
	@patch("joymedia.joymedia.doctype.media_project.media_project.frappe.get_doc")
	@patch("joymedia.joymedia.doctype.media_project.media_project.frappe.get_all")
	@patch(
		"joymedia.joymedia.doctype.media_project.media_project.filelock",
		return_value=nullcontext(),
	)
	def test_revision_copies_settings_without_mutating_previous_spec(
		self, filelock, get_all, get_doc, set_value, commit
	):
		project = MediaProject({"doctype": "Media Project", "name": "PRJ-TEST"})
		previous = frappe._dict(
			name="SPEC-00001",
			version_number=1,
			workflow_profile="WFP-00001",
			generation_workflow_version="WFV-00001",
			prompt_template_version="PTV-00001",
			total_duration_seconds=10,
			delivery_preset="Landscape",
			delivery_width=1344,
			delivery_height=768,
			generation_instructions="Keep the product centered.",
		)
		revision = MagicMock(version_number=2)
		revision.name = "SPEC-00002"
		revision.insert.return_value = revision
		get_all.return_value = [frappe._dict(name=previous.name, version_number=1)]
		get_doc.side_effect = [previous, revision]

		result = project.create_storyboard_revision()

		self.assertEqual(result["version_number"], 2)
		self.assertEqual(previous.version_number, 1)
		filelock.assert_called_once_with("joymedia-storyboard-revision-PRJ-TEST")
		revision.insert.assert_called_once_with(ignore_permissions=True)
		set_value.assert_called_once_with(
			"Media Project", "PRJ-TEST", "status", "Draft", update_modified=False
		)
		commit.assert_called_once_with()

	@patch("joymedia.joymedia.doctype.media_project.media_project.frappe.get_all")
	def test_pending_reviews_are_filtered_to_the_campaign(self, get_all):
		project = MediaProject({"doctype": "Media Project", "name": "PRJ-A"})
		get_all.side_effect = [
			["SPEC-A"],
			["SHOT-A"],
			["JOB-A"],
			["ATT-A"],
			["GART-A"],
			[frappe._dict(name="QREV-A", generation_artifact="GART-A")],
		]

		result = project.get_pending_reviews()

		self.assertEqual(result[0]["name"], "QREV-A")
		review_call = get_all.call_args_list[-1]
		self.assertEqual(review_call.kwargs["filters"]["status"], "Pending")
		self.assertEqual(
			review_call.kwargs["filters"]["generation_artifact"], ["in", ["GART-A"]]
		)

	@patch("joymedia.joymedia.doctype.media_project.media_project.frappe.get_all")
	def test_pending_reviews_returns_empty_for_campaign_without_shots(self, get_all):
		project = MediaProject({"doctype": "Media Project", "name": "PRJ-A"})
		get_all.side_effect = [["SPEC-A"], []]

		self.assertEqual(project.get_pending_reviews(), [])
		self.assertEqual(get_all.call_count, 2)
