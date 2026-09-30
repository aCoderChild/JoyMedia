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
		self._test_default_workflow = _ensure_default_h3_workflow()

	def tearDown(self):
		super().tearDown()
		frappe.db.commit()

	def test_real_customer_portal_permissions_and_tenant_isolation(self):
		from joymedia.joymedia.doctype.media_project.media_project import (
			create_project,
			generate_project_video,
			get_project_cards,
			get_project_workspace,
			save_project_video_settings,
		)

		original_user = frappe.session.user
		user_a = _create_portal_user("JoyMedia Customer A")

		try:
			frappe.set_user(user_a)
			campaign_a = create_project(
				project_name="Customer A Campaign",
				product_name="Customer A Product",
				campaign_brief="Customer A Audience",
			)
			self.assertIn("JoyMedia User", frappe.get_roles(user_a))

			cards = get_project_cards()
			self.assertIn(campaign_a.name, [card.name for card in cards])
			self.assertEqual(get_project_workspace(campaign_a.name)["project"]["name"], campaign_a.name)

			settings = save_project_video_settings(campaign_a.name, 5, "Landscape")
			self.assertEqual(settings["delivery_preset"], "Landscape")

			file_doc = _create_uploaded_file(user_a, "customer-a-product.png")
			from joymedia.services.media_asset_service import create_media_asset
			asset_result = create_media_asset(
				"Customer A Product Image",
				"Product",
				file_doc.file_url,
			)
			from joymedia.joymedia.doctype.media_project.media_project import select_project_reference
			select_project_reference(campaign_a.name, asset_result["media_asset"])

			with patch.dict(
				frappe.conf, {"comfyui_base_url": "http://comfyui.test"}, clear=False
			), patch("joymedia.services.generation_orchestrator._enqueue"), patch(
				"joymedia.services.comfyui_client.get_system_stats", return_value={}
			), patch(
				"joymedia.services.generation_orchestrator.validate_workflow_for_execution"
			), patch(
				"joymedia.joymedia.doctype.media_project.media_project.MediaProject.generate_video_plan",
				return_value=_video_plan(),
			):
				generation_result = generate_project_video(campaign_a.name)
			self.assertEqual(generation_result["status"], "Queued")
			self.assertTrue(frappe.db.exists("Generation Run", generation_result["run"]))
			media_specification = frappe.db.get_value(
				"Media Specification",
				{"media_project": campaign_a.name},
				"name",
				order_by="version_number desc",
			)
			self.assertEqual(
				frappe.db.count("Shot Specification", {"media_specification": media_specification}),
				1,
			)
		finally:
			frappe.set_user(original_user)

	def test_campaign_workspace_aggregates_assets_and_current_storyboard(self):
		campaign, specification = _create_campaign("Campaign Workspace")
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": "Workspace Product Image",
				"media_type": "Image",
				"asset_category": "Product",
				"status": "Active",
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
		campaign.append("selected_media", {"asset_version": frappe.db.get_value("Asset Version", {"media_asset": asset.name}, "name")})
		campaign.save(ignore_permissions=True)

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

		from joymedia.joymedia.doctype.media_project.media_project import get_project_workspace

		workspace = get_project_workspace(campaign.name)
		self.assertEqual(workspace["project"]["name"], campaign.name)
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
			frappe.db.get_value("Workflow", updated.workflow, "workflow_key"),
			"product_showcase",
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

	def test_create_campaign_uses_campaign_brief(self):
		from joymedia.joymedia.doctype.media_project.media_project import create_project

		campaign = create_project(
			project_name="Controlled Campaign",
			product_name="Test Product",
			campaign_brief="Test Campaign Brief",
		)

		self.assertTrue(frappe.db.exists("Media Project", campaign.name))
		self.assertEqual("Test Campaign Brief", campaign.campaign_brief)

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
	@patch("joymedia.services.generation_orchestrator.validate_workflow_for_execution")
	@patch("joymedia.services.generation_orchestrator.start_run_internal")
	def test_generate_video_returns_existing_run_on_repeat(
		self, start_run_internal, validate_workflow_for_execution, get_system_stats, filelock
	):
		campaign, specification = _create_campaign("Generation Idempotency")
		_create_shot_fixtures(specification.name, frappe.generate_hash(length=8), create_run=False)
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
	project = frappe.get_doc(
		{
			"doctype": "Media Project",
			"project_name": label,
			"product_name": "Test Product",
			"campaign_brief": "Test Campaign Brief",
			"status": "Draft",
		}
	).insert(ignore_permissions=True)
	file_doc = _create_uploaded_file(frappe.session.user, f"{label.lower().replace(' ', '-')}.png")
	asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": f"{label} Product Image",
			"media_type": "Image",
			"asset_category": "Product",
			"status": "Active",
		}
	).insert(ignore_permissions=True)
	version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": asset.name,
			"file": file_doc.file_url,
			"source": "Uploaded",
		}
	).insert(ignore_permissions=True)
	project.append("selected_media", {"asset_version": version.name})
	project.save(ignore_permissions=True)

	specification = frappe.get_doc(
		{
			"doctype": "Media Specification",
			"media_project": project.name,
			"version_number": 1,
			"status": "Draft",
			"workflow": workflow,
			"total_duration_seconds": 5,
			"delivery_preset": "Landscape",
		}
	).insert(ignore_permissions=True)

	return project, specification


def _create_portal_user(first_name):
	email = f"{frappe.generate_hash(length=12)}@example.com"
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"enabled": 1,
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True).name
	user_doc = frappe.get_doc("User", user)
	user_doc.append("roles", {"role": "JoyMedia User"})
	user_doc.save(ignore_permissions=True)
	return user


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
	run = frappe.get_doc("Generation Run", review_name)
	media_asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": f"{review_name} Final Video",
			"media_type": "Video",
			"asset_category": "Other",
			"status": "Active",
		}
	).insert(ignore_permissions=True)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{review_name}.mp4",
			"content": b"video",
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": media_asset.name,
		}
	).insert(ignore_permissions=True)
	asset_version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": media_asset.name,
			"file": file_doc.file_url,
			"source": "Generated",
		}
	)
	asset_version.db_insert()
	run.final_asset_version = asset_version.name
	run.save(ignore_permissions=True)


def _get_test_workflow():
	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_key": f"test_showcase_{frappe.generate_hash(length=6)}",
			"workflow_json": '{"load_img":{"inputs":{"image":""}},"minimax_cond":{"inputs":{"length":124}},"save_video":{"inputs":{"frame_rate":24}}}',
			"bindings": [{"binding_key": "first_frame", "node_key": "load_img", "input_name": "image", "value_source": "Generation Input", "required_input_role": "first_frame", "value_type": "File Path", "required": 1}],
		}
	).insert(ignore_permissions=True)
	return workflow.name


def _ensure_default_h3_workflow():
	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_key": "product_showcase",
			"workflow_json": (
				'{"load_img":{"inputs":{"image":""},"class_type":"VHS_LoadImagePath"},'
				'"minimax_cond":{"inputs":{"length":124},"class_type":"MiniMaxH3ImageToVideo"},'
				'"save_video":{"inputs":{"images":["dec_video",0],"frame_rate":24,'
				'"filename_prefix":"JoyMedia","loop_count":0,"format":"video/h264-mp4",'
				'"pingpong":false,"save_output":true},"class_type":"VHS_VideoCombine"}}'
			),
			"bindings": [{"binding_key": "first_frame", "node_key": "load_img", "input_name": "image", "value_source": "Generation Input", "required_input_role": "first_frame", "value_type": "File Path", "required": 1}],
		}
	).insert(ignore_permissions=True)
	return workflow.name


def _create_shot_fixtures(media_specification, suffix, create_run=True):
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
				"media_type": "Image",
				"asset_category": "Product",
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
			"status": "Draft",
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
			"artifact_role": "Primary Video",
			"generation_attempt": attempt.name,
			"media_type": "Video",
		}
	)
	artifact.db_insert()
	if not create_run:
		return shot.name

	run = frappe.get_doc(
		{
			"doctype": "Generation Run",
			"name": f"RUN-TEST-{suffix}",
			"media_specification": media_specification,
			"workflow_version": workflow,
			"requested_by": "Administrator",
			"status": "Completed",
		}
	)
	run.db_insert()
	return run.name
