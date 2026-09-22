# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

import base64
import json

import frappe
from contextlib import nullcontext
from unittest.mock import patch
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime


class IntegrationTestMediaProject(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self._original_default_workflows = frappe.get_all(
			"Workflow", filters={"is_default": 1}, pluck="name"
		)
		self._test_default_workflow = _ensure_default_h3_workflow()

	def tearDown(self):
		super().tearDown()
		frappe.db.set_value("Workflow", {"is_default": 1}, "is_default", 0)
		for workflow_name in self._original_default_workflows:
			if frappe.db.exists("Workflow", workflow_name):
				frappe.db.set_value("Workflow", workflow_name, "is_default", 1)
		if frappe.db.exists("Workflow", self._test_default_workflow):
			frappe.db.set_value(
				"Workflow",
				self._test_default_workflow,
				{"is_default": 0, "is_active": 0, "client_visible": 0},
			)
		frappe.db.commit()

	def test_real_customer_portal_permissions_and_tenant_isolation(self):
		from joymedia.joymedia.doctype.media_project.media_project import (
			apply_campaign_video_plan,
			create_business,
			create_campaign,
			create_campaign_asset,
			generate_campaign_video,
			get_campaign_cards,
			get_campaign_workspace,
			save_campaign_video_settings,
		)

		original_user = frappe.session.user
		user_a = _create_portal_user("JoyMedia Customer A")
		user_b = _create_portal_user("JoyMedia Customer B")

		try:
			frappe.set_user(user_a)
			organization_a = create_business("Customer A Business")
			frappe.clear_cache()
			frappe.set_user(user_a)
			campaign_a = create_campaign(
				project_name="Customer A Campaign",
				client_organization=organization_a.name,
				product_name="Customer A Product",
				target_audience="Customer A Audience",
			)
			self.assertIn("JoyMedia User", frappe.get_roles(user_a))
			self.assertTrue(
				frappe.db.exists(
					"User Permission",
					{
						"user": user_a,
						"allow": "Client Organization",
						"for_value": organization_a.name,
					},
				)
			)

			frappe.set_user(user_b)
			organization_b = create_business("Customer B Business")
			frappe.clear_cache()
			frappe.set_user(user_b)
			campaign_b = create_campaign(
				project_name="Customer B Campaign",
				client_organization=organization_b.name,
				product_name="Customer B Product",
				target_audience="Customer B Audience",
			)

			frappe.set_user(user_a)
			for doctype in (
				"Media Specification",
				"Generation Run",
				"Generation Attempt",
				"Quality Review",
				"Asset Version",
			):
				self.assertFalse(frappe.has_permission(doctype, "read"), doctype)

			cards = get_campaign_cards()
			self.assertEqual([card.name for card in cards], [campaign_a.name])
			self.assertEqual(get_campaign_workspace(campaign_a.name)["campaign"]["name"], campaign_a.name)

			settings = save_campaign_video_settings(campaign_a.name, 5, "Landscape")
			self.assertEqual(settings["delivery_preset"], "Landscape")

			file_doc = _create_uploaded_file(user_a, "customer-a-product.png")
			create_campaign_asset(
				campaign_a.name,
				"Customer A Product Image",
				"Product",
				file_doc.file_url,
			)

			apply_campaign_video_plan(campaign_a.name, json.dumps(_video_plan()))
			with patch.dict(
				frappe.conf, {"comfyui_base_url": "http://comfyui.test"}, clear=False
			), patch("joymedia.services.generation_orchestrator._enqueue"), patch(
				"joymedia.services.comfyui_client.get_system_stats", return_value={}
			):
				generation_result = generate_campaign_video(campaign_a.name)
			self.assertEqual(generation_result["status"], "Queued")

			with self.assertRaises(frappe.PermissionError):
				get_campaign_workspace(campaign_b.name)
			with self.assertRaises(frappe.PermissionError):
				save_campaign_video_settings(campaign_b.name, 8, "Landscape")
			with self.assertRaises(frappe.PermissionError):
				create_campaign_asset(
					campaign_b.name,
					"Customer B Product Image",
					"Product",
					file_doc.file_url,
				)
			with self.assertRaises(frappe.PermissionError):
				apply_campaign_video_plan(campaign_b.name, json.dumps(_video_plan()))
			with self.assertRaises(frappe.PermissionError):
				generate_campaign_video(campaign_b.name)
		finally:
			frappe.set_user(original_user)

	def test_real_customer_review_permissions_and_tenant_isolation(self):
		from joymedia.joymedia.doctype.media_project.media_project import (
			approve_campaign_review,
			create_business,
			create_campaign,
			reject_campaign_review,
			regenerate_campaign_review,
			stream_campaign_review,
		)

		original_user = frappe.session.user
		user_a = _create_portal_user("JoyMedia Review Customer A")
		user_b = _create_portal_user("JoyMedia Review Customer B")

		try:
			frappe.set_user(user_a)
			organization_a = create_business("Review Customer A Business")
			frappe.clear_cache()
			frappe.set_user(user_a)
			campaign_a = create_campaign(
				project_name="Review Customer A Campaign",
				client_organization=organization_a.name,
				product_name="Customer A Product",
				target_audience="Customer A Audience",
			)
			frappe.set_user(user_b)
			organization_b = create_business("Review Customer B Business")
			frappe.clear_cache()
			frappe.set_user(user_b)
			campaign_b = create_campaign(
				project_name="Review Customer B Campaign",
				client_organization=organization_b.name,
				product_name="Customer B Product",
				target_audience="Customer B Audience",
			)

			# Give each campaign a current specification before creating review fixtures.
			frappe.set_user("Administrator")
			campaign_a.save_video_settings(8, "Landscape")
			campaign_b.save_video_settings(8, "Landscape")
			specification_a = get_latest_media_specification_for_test(campaign_a.name)
			specification_b = get_latest_media_specification_for_test(campaign_b.name)
			review_a = _create_pending_review(specification_a.name, frappe.generate_hash(length=8))
			review_b = _create_pending_review(specification_b.name, frappe.generate_hash(length=8))
			_file_review_artifact(review_a)
			_file_review_artifact(review_b)

			frappe.set_user(user_a)
			stream_campaign_review(campaign_a.name, review_a)
			self.assertIn(frappe.local.response.filecontent, ("video", b"video"))
			with patch(
				"joymedia.joymedia.doctype.asset_version.asset_version.AssetVersion.set_file_metadata"
			):
				approve_campaign_review(campaign_a.name, review_a)

			review_for_regeneration = _create_pending_review(
				specification_a.name, frappe.generate_hash(length=8)
			)
			frappe.db.set_value("Quality Review", review_for_regeneration, "status", "Pending")
			reject_campaign_review(campaign_a.name, review_for_regeneration, "Needs another take")
			with patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.create_qa_retry_attempt_internal",
				return_value=type("RetryAttempt", (), {"name": "ATT-PORTAL-RETRY"})(),
			), patch(
				"joymedia.services.generation_runner.submit_attempt",
				return_value={"deferred": True},
			):
				regeneration = regenerate_campaign_review(
					campaign_a.name, review_for_regeneration
				)
			self.assertTrue(regeneration["deferred"])

			with self.assertRaises(frappe.PermissionError):
				stream_campaign_review(campaign_b.name, review_b)
			with self.assertRaises(frappe.PermissionError):
				approve_campaign_review(campaign_b.name, review_b)
			with self.assertRaises(frappe.PermissionError):
				reject_campaign_review(campaign_b.name, review_b)
			with self.assertRaises(frappe.PermissionError):
				regenerate_campaign_review(campaign_b.name, review_b)
		finally:
			frappe.set_user(original_user)
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
			frappe.db.get_value("Workflow", updated.workflow, "workflow_code"),
			"MINIMAX-H3",
		)

	def test_customer_video_style_selects_and_snapshots_workflow(self):
		from joymedia.joymedia.doctype.media_project.media_project import get_video_styles

		campaign, specification = _create_campaign("Video Style")
		result = campaign.save_video_settings(8, "Landscape", "product_showcase")
		updated = frappe.get_doc("Media Specification", result["media_specification"])

		self.assertEqual(updated.video_style, "product_showcase")
		self.assertEqual(
			frappe.db.get_value("Workflow", updated.workflow, "workflow_key"),
			"product_showcase",
		)
		self.assertTrue(
			any(style.workflow_key == "product_showcase" for style in get_video_styles())
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
		self.assertEqual(revision.workflow, previous.workflow)
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
	@patch("joymedia.services.comfyui_client.get_system_stats", return_value={})
	@patch("joymedia.services.generation_orchestrator.start_run_internal")
	def test_generate_video_returns_existing_run_on_repeat(
		self, start_run_internal, get_system_stats, filelock
	):
		campaign, specification = _create_campaign("Generation Idempotency")
		_create_pending_review(specification.name, frappe.generate_hash(length=8))

		def queue_run(run_name):
			frappe.db.set_value("Generation Run", run_name, "status", "Queued")
			return {"name": run_name, "status": "Queued"}

		start_run_internal.side_effect = queue_run
		with patch.dict(
			frappe.conf, {"comfyui_base_url": "http://comfyui.test"}, clear=False
		):
			first_result = campaign.generate_video()
			second_result = campaign.generate_video()

		self.assertEqual(second_result, first_result)
		self.assertEqual(
			frappe.db.count("Generation Run", {"media_specification": specification.name}),
			1,
		)
		start_run_internal.assert_called_once_with(first_result["run"])


def _create_campaign(label):
	workflow = _get_test_workflow()
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
			"workflow": workflow,
			"total_duration_seconds": 5,
			"delivery_preset": "Landscape",
		}
	).insert(ignore_permissions=True)

	return campaign, specification


def _create_portal_user(first_name):
	email = f"{frappe.generate_hash(length=12)}@example.com"
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"enabled": 1,
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True).name


def _create_uploaded_file(owner, file_name):
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": base64.b64decode(
				"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
			),
			"is_private": 1,
			"owner": owner,
		}
	).insert(ignore_permissions=True)


def _video_plan():
	return {
		"shots": [
			{
				"shot_number": 1,
				"camera": "A controlled product close-up.",
				"subject": "The product centered in frame.",
				"motion": "A slow forward camera movement.",
				"lighting": "Soft commercial lighting with a clean background.",
				"audio": "Subtle product movement and ambient sound.",
				"reference_image_index": 1,
				"generation_prompt": "A clean product commercial with a slow forward camera movement.",
			}
		]
	}


def get_latest_media_specification_for_test(media_project):
	return frappe.get_doc(
		"Media Specification",
		frappe.db.get_value(
			"Media Specification",
			{"media_project": media_project},
			"name",
			order_by="version_number desc",
		),
	)


def _file_review_artifact(review_name):
	artifact_name = frappe.db.get_value("Quality Review", review_name, "generation_artifact")
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{review_name}.mp4",
			"content": b"video",
			"is_private": 1,
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Generation Artifact", artifact_name, "frappe_file", file_doc.file_url)


def _get_test_workflow():
	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_code": f"TEST-MINIMAX-H3-{frappe.generate_hash(length=8)}",
			"workflow_key": f"test_showcase_{frappe.generate_hash(length=6)}",
			"version_number": 1,
			"version_label": "Integration Test H3",
			"status": "Testing",
			"is_default": 0,
			"workflow_json": '{"load_img":{"inputs":{"image":""}},"minimax_cond":{"inputs":{"length":124}},"save_video":{"inputs":{"frame_rate":24}}}',
		}
	).insert(ignore_permissions=True)
	workflow.append(
		"bindings",
		{
			"binding_key": "first_frame",
			"node_key": "load_img",
			"input_name": "image",
			"value_source": "Generation Input",
			"required_input_role": "first_frame",
			"value_type": "File Path",
			"required": 1,
		},
	)
	workflow.save(ignore_permissions=True)
	return workflow.name


def _ensure_default_h3_workflow():
	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_code": "MINIMAX-H3",
			"workflow_key": "product_showcase",
			"version_number": 1,
			"version_label": "Integration MiniMax H3",
			"client_name": "Product Showcase",
			"client_description": "Integration-only product showcase.",
			"client_visible": 1,
			"is_active": 1,
			"status": "Draft",
			"is_default": 0,
			"workflow_json": (
				'{"load_img":{"inputs":{"image":""}},'
				'"minimax_cond":{"inputs":{"length":124}},'
				'"save_video":{"inputs":{"frame_rate":24}}}'
			),
		}
	).insert(ignore_permissions=True)
	workflow.append(
		"bindings",
		{
			"binding_key": "first_frame",
			"node_key": "load_img",
			"input_name": "image",
			"value_source": "Generation Input",
			"required_input_role": "first_frame",
			"value_type": "File Path",
			"required": 1,
		},
	)
	workflow.status = "Testing"
	workflow.save(ignore_permissions=True)
	frappe.db.set_value("Workflow", {"is_default": 1}, "is_default", 0)
	workflow.is_default = 1
	workflow.save(ignore_permissions=True)
	return workflow.name


def _create_pending_review(media_specification, suffix):
	workflow = frappe.db.get_value(
		"Media Specification", media_specification, "workflow"
	)
	media_project = frappe.db.get_value(
		"Media Specification", media_specification, "media_project"
	)
	required_input_roles = frappe.get_all(
		"Workflow Binding",
		{
			"parent": workflow,
			"parenttype": "Workflow",
			"parentfield": "bindings",
			"value_source": "Generation Input",
			"required": 1,
		},
		pluck="required_input_role",
	)
	generation_inputs = []
	for required_input_role in set(required_input_roles):
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": f"Review Input {suffix} {required_input_role}",
				"asset_scope": "Project",
				"media_type": "Image",
				"asset_category": "Product",
				"media_project": media_project,
			}
		).insert(ignore_permissions=True)
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"review-input-{suffix}-{required_input_role}.png",
				"content": base64.b64decode(
					"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
				),
				"is_private": 1,
				"attached_to_doctype": "Media Asset",
				"attached_to_name": asset.name,
			}
		).insert(ignore_permissions=True)
		asset_version = frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": asset.name,
				"file": file_doc.file_url,
				"source": "Uploaded",
			}
		).insert(ignore_permissions=True)
		generation_inputs.append(
			{
				"input_role": required_input_role,
				"asset_version": asset_version.name,
			}
		)
	shot_number = frappe.db.sql(
		"""
		select coalesce(max(shot_number), 0) + 1
		from `tabShot Specification`
		where media_specification = %s
		""",
		media_specification,
	)[0][0]
	shot = frappe.get_doc(
		{
			"doctype": "Shot Specification",
			"name": f"SHOT-TEST-{suffix}",
			"media_specification": media_specification,
			"shot_number": shot_number,
			"duration_seconds": 5,
			"planned_frame_count": 120,
			"subject_identity": "Test subject",
			"action_plot": "Test motion",
			"generation_prompt": "A concise test generation prompt.",
			"generation_inputs": generation_inputs,
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
			"workflow_version": workflow,
			"prompt_text": "Test generation prompt.",
			"prompt_hash": "test-prompt-hash",
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
