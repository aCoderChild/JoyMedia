# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime


class IntegrationTestMediaProject(IntegrationTestCase):
	def test_pending_reviews_are_isolated_between_campaigns(self):
		campaign_a, specification_a = _create_campaign("Review Isolation A")
		campaign_b, specification_b = _create_campaign("Review Isolation B")
		suffix_a = frappe.generate_hash(length=8)
		suffix_b = frappe.generate_hash(length=8)

		review_a = _create_pending_review(specification_a.name, suffix_a)
		_create_pending_review(specification_b.name, suffix_b)

		reviews = campaign_a.get_pending_reviews()

		self.assertEqual([review["name"] for review in reviews], [review_a])
		self.assertNotIn(f"QREV-TEST-{suffix_b}", [review["name"] for review in reviews])

	def test_storyboard_revision_is_persisted_without_mutating_previous_spec(self):
		campaign, specification = _create_campaign("Revision Persistence")
		specification.generation_instructions = "Keep the original product framing."
		specification.save(ignore_permissions=True)
		specification.status = "Ready"
		specification.save(ignore_permissions=True)
		campaign.status = "Completed"

		result = campaign.create_storyboard_revision()

		previous = frappe.get_doc("Media Specification", specification.name)
		revision = frappe.get_doc("Media Specification", result["media_specification"])

		self.assertEqual(previous.version_number, 1)
		self.assertEqual(previous.status, "Ready")
		self.assertEqual(revision.version_number, 2)
		self.assertEqual(revision.status, "Draft")
		self.assertEqual(revision.media_project, campaign.name)
		self.assertEqual(revision.workflow_profile, previous.workflow_profile)
		self.assertEqual(
			revision.generation_workflow_version,
			previous.generation_workflow_version,
		)
		self.assertEqual(revision.prompt_template_version, previous.prompt_template_version)
		self.assertEqual(revision.total_duration_seconds, previous.total_duration_seconds)
		self.assertEqual(revision.delivery_preset, previous.delivery_preset)
		self.assertEqual(revision.generation_instructions, previous.generation_instructions)
		self.assertEqual(frappe.db.get_value("Media Project", campaign.name, "status"), "Draft")


def _create_campaign(label):
	workflow_profile = _get_test_workflow_profile()
	organization = frappe.get_doc(
		{
			"doctype": "Client Organization",
			"organization_name": f"{label} Business",
		}
	).insert(ignore_permissions=True)

	campaign = frappe.get_doc(
		{
			"doctype": "Media Project",
			"project_name": label,
			"client_organization": organization.name,
			"product_name": "Test Product",
			"target_audience": "Test Audience",
			"status": "Draft",
		}
	).insert(ignore_permissions=True)

	specification = frappe.get_doc(
		{
			"doctype": "Media Specification",
			"media_project": campaign.name,
			"version_number": 1,
			"status": "Draft",
			"workflow_profile": workflow_profile,
			"total_duration_seconds": 10,
			"delivery_preset": "Landscape",
		}
	).insert(ignore_permissions=True)

	return campaign, specification


def _get_test_workflow_profile():
	profile_name = frappe.db.get_value(
		"Workflow Profile",
		{"workflow_code": "TEST-H3-CAMPAIGN"},
		"name",
	)
	if profile_name:
		return profile_name

	profile = frappe.get_doc(
		{
			"doctype": "Workflow Profile",
			"profile_name": "Campaign Integration H3",
			"workflow_code": "TEST-H3-CAMPAIGN",
			"status": "Active",
		}
	).insert(ignore_permissions=True)

	workflow_version = frappe.get_doc(
		{
			"doctype": "Workflow Version",
			"workflow_profile": profile.name,
			"version_number": 1,
			"version_label": "Integration Test H3",
			"status": "Testing",
			"workflow_json": '{"minimax_cond":{"inputs":{"length":124}},"save_video":{"inputs":{"frame_rate":24}}}',
		}
	).insert(ignore_permissions=True)

	prompt_template = frappe.get_doc(
		{
			"doctype": "Prompt Template",
			"template_name": "Campaign Integration Prompt",
			"template_code": "TEST-CAMPAIGN-PROMPT",
			"workflow_profile": profile.name,
			"status": "Active",
		}
	).insert(ignore_permissions=True)

	prompt_version = frappe.get_doc(
		{
			"doctype": "Prompt Template Version",
			"prompt_template": prompt_template.name,
			"version_number": 1,
			"version_label": "Integration Test Prompt",
			"status": "Testing",
			"template_body": "[Subject] {subject_identity}",
		}
	).insert(ignore_permissions=True)

	profile.default_workflow_version = workflow_version.name
	profile.default_prompt_template_version = prompt_version.name
	profile.save(ignore_permissions=True)
	return profile.name


def _create_pending_review(media_specification, suffix):
	shot = frappe.get_doc(
		{
			"doctype": "Shot Specification",
			"name": f"SHOT-TEST-{suffix}",
			"media_specification": media_specification,
			"shot_number": 1,
			"duration_seconds": 10,
			"subject_identity": "Test subject",
			"action_plot": "Test motion",
		}
	).insert(ignore_permissions=True)

	job = frappe.get_doc(
		{
			"doctype": "Generation Job",
			"name": f"JOB-TEST-{suffix}",
			"shot_specification": shot.name,
			"requested_by": "Administrator",
			"requested_variants": 1,
			"status": "Draft",
			"priority": "Normal",
			"workflow_version": "WFV-00001",
			"compiled_prompt": f"CPR-TEST-{suffix}",
			"segment_index": 1,
			"segment_frame_count": 1,
		}
	)
	job.db_insert()

	attempt = frappe.get_doc(
		{
			"doctype": "Generation Attempt",
			"name": f"ATT-TEST-{suffix}",
			"generation_job": job.name,
			"attempt_number": 1,
			"seed": 1,
			"status": "Completed",
			"completed_at": now_datetime(),
		}
	)
	attempt.db_insert()

	artifact = frappe.get_doc(
		{
			"doctype": "Generation Artifact",
			"name": f"GART-TEST-{suffix}",
			"artifact_key": f"test-artifact-{suffix}",
			"generation_attempt": attempt.name,
			"media_type": "Video",
			"lifecycle_status": "Temporary",
		}
	)
	artifact.db_insert()
	frappe.db.set_value("Generation Attempt", attempt.name, "output_artifact", artifact.name)

	review = frappe.get_doc(
		{
			"doctype": "Quality Review",
			"name": f"QREV-TEST-{suffix}",
			"generation_artifact": artifact.name,
			"status": "Pending",
		}
	)
	review.db_insert()
	return review.name
