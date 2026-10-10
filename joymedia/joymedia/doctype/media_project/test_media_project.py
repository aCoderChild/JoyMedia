# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

import base64
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestMediaProject(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		# The code under test commits; without this every run leaves its projects behind.
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.workflow = _ensure_workflow()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_project_uses_video_idea_as_single_creative_brief(self):
		from joymedia.api.projects import create_project

		project = create_project(
			project_name="Prompt Project",
			product_name="Test Product",
			video_idea="Create an energetic product commercial.",
		)
		self.assertEqual(project.video_idea, "Create an energetic product commercial.")
		self.assertFalse(frappe.get_meta("Media Project").has_field("campaign_brief"))
		self.assertFalse(frappe.get_meta("Media Project").has_field("reference_template"))

	def test_selected_media_supports_image_video_and_audio(self):
		from joymedia.services.project_context import _get_project_selected_assets

		project, _ = _create_project("Reference Media", self.workflow)
		for media_type, extension in (("Image", "png"), ("Video", "mp4"), ("Audio", "wav")):
			asset, version = _create_asset_version(project, media_type, extension)
			project.append("selected_media", {"asset_version": version.name})
		project.save(ignore_permissions=True)
		selected = _get_project_selected_assets(project)
		self.assertEqual({row.media_type for row in selected}, {"Image", "Video", "Audio"})
		self.assertTrue(all("?fid=" in row.file for row in selected))

	def test_project_reference_key_uses_logical_asset_name_and_resolves_collisions(self):
		project, _ = _create_project("Reference Keys", self.workflow)
		first_asset, first_version = _create_asset_version(project, "Image", "png")
		first_asset.asset_name = "Nike Air Max"
		first_asset.save(ignore_permissions=True)
		second_asset, second_version = _create_asset_version(project, "Image", "png")
		second_asset.asset_name = "Nike Air Max"
		second_asset.save(ignore_permissions=True)
		project.append("selected_media", {"asset_version": first_version.name})
		project.append("selected_media", {"asset_version": second_version.name})
		project.save(ignore_permissions=True)
		keys = [row.reference_key for row in project.selected_media]
		self.assertEqual(keys, ["nike_air_max", "nike_air_max_2"])
		self.assertNotIn(first_version.name.lower(), keys)

	def test_workspace_exposes_business_data_not_raw_artifacts(self):
		from joymedia.api.projects import get_project_workspace
		from joymedia.services.video_plan_service import apply_video_plan

		project, _ = _create_project("Workspace", self.workflow)
		asset, version = _create_asset_version(project, "Image", "png")
		project.append("selected_media", {"asset_version": version.name})
		project.save(ignore_permissions=True)
		apply_video_plan(project.name, {
			"shots": [{
				"shot_number": 1,
				"duration_seconds": 5,
				"generation_prompt": "A clean product reveal.",
			}]
		})
		workspace = get_project_workspace(project.name)
		self.assertEqual(workspace["project"]["video_idea"], project.video_idea)
		self.assertEqual(workspace["storyboard"][0]["generation_prompt"], "A clean product reveal.")
		self.assertNotIn("outputs", workspace)
		self.assertEqual(workspace["assets"][0]["asset_version"], version.name)

	@patch("joymedia.services.project_context._get_asset_version_file_url")
	@patch("joymedia.services.project_context.frappe.db.get_value")
	@patch("joymedia.services.project_context.frappe.get_all")
	def test_shot_progress_is_weighted_by_segment_frames(self, get_all, get_value, get_file_url):
		from joymedia.services.project_context import _aggregate_shot_progress

		get_all.return_value = [
			frappe._dict(
				shot="SHOT-00001",
				status="Completed",
				progress=100,
				error_summary=None,
				segment_frame_count=120,
			),
			frappe._dict(
				shot="SHOT-00001",
				status="Running",
				progress=0,
				error_summary=None,
				segment_frame_count=60,
			),
		]
		get_value.return_value = frappe._dict(
			shot_number=1,
			shot_name="Shot 1",
			selected_output_asset_version=None,
		)
		get_file_url.return_value = None

		result = _aggregate_shot_progress("RUN-00001")

		self.assertEqual(result[0]["status"], "Running")
		self.assertAlmostEqual(result[0]["progress"], 66.666666, places=4)

	def test_shot_can_preserve_multiple_references_with_one_role(self):
		from joymedia.services.video_plan_service import apply_video_plan

		project, _ = _create_project("Multiple References", self.workflow)
		first_asset, first_version = _create_asset_version(project, "Image", "png")
		first_asset.asset_name = "Shoe Front"
		first_asset.save(ignore_permissions=True)
		second_asset, second_version = _create_asset_version(project, "Image", "png")
		second_asset.asset_name = "Shoe Side"
		second_asset.save(ignore_permissions=True)
		project.append("selected_media", {"asset_version": first_version.name})
		project.append("selected_media", {"asset_version": second_version.name})
		project.save(ignore_permissions=True)
		keys = [row.reference_key for row in project.selected_media]
		apply_video_plan(project.name, {
			"shots": [{
				"shot_number": 1,
				"duration_seconds": 5,
				"generation_prompt": "Show the shoe from multiple angles.",
				"references": [
					{"reference_key": keys[0], "usage_role": "product_reference"},
					{"reference_key": keys[1], "usage_role": "product_reference"},
				],
			}],
		})
		shot = frappe.get_doc("Shot", frappe.db.get_value("Shot", {"media_project": project.name}))
		self.assertEqual(
			[(row.reference_role, row.asset_version) for row in shot.generation_inputs if row.reference_role == "product_reference"],
			[("product_reference", first_version.name), ("product_reference", second_version.name)],
		)
		self.assertEqual(
			[(row.reference_role, row.asset_version) for row in shot.generation_inputs if row.reference_role == "first_frame"],
			[("first_frame", first_version.name)],
		)

	def test_planning_context_tracks_prompt_assets_settings_and_global_instructions(self):
		from joymedia.services.project_context import _build_planning_context

		project, _ = _create_project("Planning Context", self.workflow)
		context, first_hash = _build_planning_context(project)
		self.assertEqual(context["video_idea"], project.video_idea)
		self.assertEqual(context["global_instructions"], "Keep the product identity consistent.")

		project.video_idea = "A brighter revised campaign."
		project.save(ignore_permissions=True)
		_, changed_hash = _build_planning_context(project)
		self.assertNotEqual(first_hash, changed_hash)

	def test_storyboard_revision_preserves_prompt_and_supersedes_previous_spec(self):
		from joymedia.services.video_plan_service import apply_video_plan

		project, _ = _create_project("Storyboard Revision", self.workflow)
		_attach_image_reference(project, "Revision Reference")
		apply_video_plan(project.name, {
			"shots": [{
				"shot_number": 1,
				"duration_seconds": 5,
				"generation_prompt": "Original shot prompt.",
			}]
		})
		project.db_set("status", "Completed", update_modified=False)

		result = project.create_storyboard_revision()
		new_shot = frappe.db.get_value(
			"Shot", {"media_project": project.name}, ["generation_prompt"], as_dict=True
		)
		self.assertEqual(result["media_project"], project.name)
		self.assertEqual(new_shot.generation_prompt, "Original shot prompt.")

	def test_generation_workflow_owns_adapter_without_model_profile_doctype(self):
		workflow = frappe.get_doc("Generation Workflow", self.workflow)
		self.assertEqual(workflow.adapter_key, "comfyui_generic")
		self.assertFalse(frappe.db.exists("DocType", "AI Model Profile"))

	@patch("joymedia.services.generation_orchestrator.start_run_internal")
	@patch("joymedia.services.generation_orchestrator.validate_generation_preflight")
	def test_generation_recalculates_shots_before_freezing_run_snapshot(
		self, validate_preflight, start_run
	):
		from joymedia.services.project_context import build_project_snapshot
		from joymedia.services.shot_duration_planner import recalculate_shot_durations
		from joymedia.services.video_plan_service import apply_video_plan

		project, _ = _create_project("Snapshot Duration Order", self.workflow)
		_attach_image_reference(project, "Snapshot Reference")
		apply_video_plan(project.name, {
			"shots": [{
				"shot_number": 1,
				"duration_seconds": 5,
				"generation_prompt": "A product reveal.",
			}],
		})
		project.reload()
		events = []

		def recalculate(media_project_name):
			events.append("recalculate")
			return recalculate_shot_durations(media_project_name)

		def snapshot(current_project):
			events.append("snapshot")
			return build_project_snapshot(current_project)

		start_run.return_value = {"status": "Queued"}
		with patch(
			"joymedia.services.shot_duration_planner.recalculate_shot_durations",
			side_effect=recalculate,
		), patch(
			"joymedia.joymedia.doctype.media_project.media_project.build_project_snapshot",
			side_effect=snapshot,
		):
			result = project.generate_video()

		self.assertEqual(result["status"], "Queued")
		self.assertEqual(events, ["recalculate", "snapshot"])
		start_run.assert_called_once()


def _create_project(label, workflow):
	project = frappe.get_doc({
		"doctype": "Media Project",
		"project_name": label,
		"product_name": "Test Product",
		"video_idea": "Create a premium product showcase.",
		"total_duration_seconds": 5,
		"delivery_preset": "Landscape",
		"delivery_width": 1344,
		"delivery_height": 768,
		"generation_mode": "Continuous",
		"global_instructions": "Keep the product identity consistent.",
		"workflow": workflow,
	}).insert(ignore_permissions=True)
	return project, None


def _create_asset_version(project, media_type, extension):
	asset = frappe.get_doc({
		"doctype": "Media Asset",
		"asset_name": f"{media_type} Reference {frappe.generate_hash(length=5)}",
		"media_type": media_type,
		"asset_category": "Reference" if media_type != "Image" else "Product",
		"asset_scope": "Library",
		"status": "Active",
	}).insert(ignore_permissions=True)

	if media_type == "Image":
		content = base64.b64decode(
			"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
		)
	else:
		# Metadata extraction for video is not the focus of this relationship test.
		content = b"reference-media"
	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": f"reference-{frappe.generate_hash(length=5)}.{extension}",
		"content": content,
		"is_private": 1,
	}).insert(ignore_permissions=True)
	version = frappe.get_doc({
		"doctype": "Asset Version",
		"media_asset": asset.name,
		"file": file_doc.file_url,
		"source": "Uploaded",
	})
	if media_type in ("Video", "Audio"):
		# Avoid media probing in this relation-only fixture.
		with patch.object(version, "set_file_metadata"):
			version.insert(ignore_permissions=True)
	else:
		version.insert(ignore_permissions=True)
	return asset, version


def _attach_image_reference(project, asset_name):
	asset, version = _create_asset_version(project, "Image", "png")
	asset.asset_name = asset_name
	asset.save(ignore_permissions=True)
	project.append("selected_media", {"asset_version": version.name})
	project.save(ignore_permissions=True)


def _ensure_workflow():
	workflow = frappe.get_doc({
		"doctype": "Generation Workflow",
		"workflow_key": f"product_showcase_{frappe.generate_hash(length=5)}",
		"adapter_key": "comfyui_generic",
		"workflow_json": (
			'{"load_img":{"inputs":{"image":""},"class_type":"VHS_LoadImagePath"},'
			'"dec_video":{"inputs":{},"class_type":"VAEDecode"},'
			'"save_video":{"inputs":{"images":["dec_video",0],"frame_rate":24,'
			'"filename_prefix":"JoyMedia","loop_count":0,"format":"video/h264-mp4",'
			'"pingpong":false,"save_output":true},"class_type":"VHS_VideoCombine"}}'
		),
		"execution_spec": '{"parameters":[],"metadata":{"frame_count":124,"output_fps":24,"produces_video":1},"outputs":{"primary":{"node_key":"save_video","media_type":"Video"}}}',
		"bindings": [{
			"binding_key": "first_frame",
			"node_key": "load_img",
			"input_name": "image",
			"required_input_role": "first_frame",
			"value_type": "File Path",
			"required": 1,
		}, {
			"binding_key": "product_reference",
			"node_key": "load_img",
			"input_name": "image",
			"required_input_role": "product_reference",
			"value_type": "File Paths",
			"accepted_media_type": "Image",
			"allow_multiple": 1,
			"required": 0,
		}],
	}).insert(ignore_permissions=True)
	return workflow.name
