# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

import base64

import frappe
from contextlib import nullcontext
from unittest.mock import patch
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime


class IntegrationTestMediaProject(IntegrationTestCase):
	def test_campaign_workspace_aggregates_assets_and_current_storyboard(self):
		campaign, specification = _create_campaign("Campaign Workspace")
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": "Workspace Product Image",
				"asset_scope": "Project",
				"media_type": "Image",
				"asset_category": "Product",
				"media_project": campaign.name,
				"client_organization": campaign.client_organization,
			}
		).insert(ignore_permissions=True)
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "workspace-product.png",
				"content": base64.b64decode(
					"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
				),
				"is_private": 1,
				"attached_to_doctype": "Media Asset",
				"attached_to_name": asset.name,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": asset.name,
				"file": file_doc.file_url,
				"source": "Uploaded",
			}
		).insert(ignore_permissions=True)

		from joymedia.services.video_plan_service import apply_video_plan

		apply_video_plan(
			specification.name,
			{
				"shots": [
					{
						"shot_number": 1,
						"camera": "Camera",
						"subject": "Subject",
						"motion": "Motion",
						"lighting": "Lighting",
						"audio": "Audio",
					}
				]
			},
		)

		from joymedia.joymedia.doctype.media_project.media_project import get_campaign_workspace

		workspace = get_campaign_workspace(campaign.name)
		self.assertEqual(workspace["campaign"]["name"], campaign.name)
		self.assertEqual(workspace["video_settings"]["name"], specification.name)
		self.assertEqual(workspace["storyboard"][0]["shot_number"], 1)
		self.assertEqual(workspace["assets"][0]["file"], file_doc.file_url)
		self.assertIsNone(workspace["production"])

	def test_video_settings_create_and_update_latest_draft_specification(self):
		campaign, specification = _create_campaign("Video Settings")
		frappe.delete_doc("Media Specification", specification.name, ignore_permissions=True)

		created_result = campaign.save_video_settings(8, "Portrait")
		result = campaign.save_video_settings(12, "Square")
		updated = frappe.get_doc("Media Specification", created_result["media_specification"])

		self.assertEqual(result["media_specification"], created_result["media_specification"])
		self.assertEqual(updated.total_duration_seconds, 12)
		self.assertEqual(updated.delivery_preset, "Square")
		self.assertEqual(updated.delivery_width, 1024)
		self.assertEqual(updated.delivery_height, 1024)
		self.assertEqual(
			frappe.db.get_value("Workflow Profile", updated.workflow_profile, "workflow_code"),
			"MINIMAX-H3",
		)

	@patch("joymedia.joymedia.doctype.media_project.media_project.frappe.has_permission")
	def test_create_campaign_uses_controlled_business_access(self, has_permission):
		organization = frappe.get_doc(
			{
				"doctype": "Client Organization",
				"organization_name": "Controlled Campaign Business",
			}
		).insert(ignore_permissions=True)

		from joymedia.joymedia.doctype.media_project.media_project import create_campaign

		campaign = create_campaign(
			project_name="Controlled Campaign",
			client_organization=organization.name,
			product_name="Test Product",
			target_audience="Test Audience",
		)

		self.assertTrue(frappe.db.exists("Media Project", campaign.name))
		has_permission.assert_called_once_with(
		"Client Organization", "read", organization.name, throw=True
		)

	def test_draft_storyboard_can_be_replaced_before_generation(self):
		from joymedia.services.video_plan_service import apply_video_plan

		campaign, specification = _create_campaign("Storyboard Replacement")
		first_plan = {
			"shots": [
				{
					"shot_number": 1,
					"camera": "First camera",
					"subject": "First subject",
					"motion": "First motion",
					"lighting": "First lighting",
					"audio": "First audio",
				}
			]
		}
		second_plan = {
			"shots": [
				{
					"shot_number": 1,
					"camera": "Second camera",
					"subject": "Second subject",
					"motion": "Second motion",
					"lighting": "Second lighting",
					"audio": "Second audio",
				}
			]
		}

		first_shots = apply_video_plan(specification.name, first_plan)
		second_shots = apply_video_plan(specification.name, second_plan)

		self.assertEqual(len(first_shots), 1)
		self.assertEqual(len(second_shots), 1)
		self.assertEqual(
			frappe.db.count("Shot Specification", {"media_specification": specification.name}),
			1,
		)
		self.assertEqual(
			frappe.db.get_value("Shot Specification", second_shots[0], "subject_identity"),
			"Second subject",
		)

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
		repeated_result = campaign.create_storyboard_revision()

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
		self.assertEqual(repeated_result, result)
		self.assertEqual(
			frappe.db.count("Media Specification", {"media_project": campaign.name}),
			2,
		)

	@patch(
		"joymedia.joymedia.doctype.media_project.media_project.filelock",
		return_value=nullcontext(),
	)
	@patch("joymedia.services.generation_orchestrator.start_run_internal")
	def test_generate_video_returns_existing_run_on_repeat(self, start_run_internal, filelock):
		campaign, specification = _create_campaign("Generation Idempotency")
		_create_pending_review(specification.name, frappe.generate_hash(length=8))

		def queue_run(run_name):
			frappe.db.set_value("Generation Run", run_name, "status", "Queued")
			return {"name": run_name, "status": "Queued"}

		start_run_internal.side_effect = queue_run
		first_result = campaign.generate_video()
		second_result = campaign.generate_video()

		self.assertEqual(second_result, first_result)
		self.assertEqual(
			frappe.db.count("Generation Run", {"media_specification": specification.name}),
			1,
		)
		start_run_internal.assert_called_once_with(first_result["run"])


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
		{"workflow_code": "MINIMAX-H3"},
		"name",
	)
	if profile_name:
		return profile_name

	profile = frappe.get_doc(
		{
			"doctype": "Workflow Profile",
			"profile_name": "Campaign Integration H3",
			"workflow_code": "MINIMAX-H3",
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
	workflow_version = frappe.db.get_value(
		"Media Specification", media_specification, "generation_workflow_version"
	)
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
			"workflow_version": workflow_version,
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
