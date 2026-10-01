# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

import base64
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestMediaProject(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.workflow = _ensure_workflow()

	def test_project_uses_video_idea_as_single_creative_brief(self):
		from joymedia.joymedia.doctype.media_project.media_project import create_project

		project = create_project(
			project_name="Prompt Project",
			product_name="Test Product",
			video_idea="Create an energetic product commercial.",
		)
		self.assertEqual(project.video_idea, "Create an energetic product commercial.")
		self.assertFalse(frappe.get_meta("Media Project").has_field("campaign_brief"))
		self.assertFalse(frappe.get_meta("Media Project").has_field("reference_template"))

	def test_selected_media_supports_image_video_and_audio(self):
		from joymedia.joymedia.doctype.media_project.media_project import _get_project_selected_assets

		project, _ = _create_project("Reference Media", self.workflow)
		for media_type, extension in (("Image", "png"), ("Video", "mp4"), ("Audio", "wav")):
			asset, version = _create_asset_version(project, media_type, extension)
			project.append("selected_media", {"asset_version": version.name})
		project.save(ignore_permissions=True)
		selected = _get_project_selected_assets(project)
		self.assertEqual({row.media_type for row in selected}, {"Image", "Video", "Audio"})

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
		from joymedia.joymedia.doctype.media_project.media_project import get_project_workspace
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
			[(row.reference_role, row.asset_version) for row in shot.generation_inputs],
			[("product_reference", first_version.name), ("product_reference", second_version.name)],
		)

	def test_planning_context_tracks_prompt_assets_settings_and_global_instructions(self):
		from joymedia.joymedia.doctype.media_project.media_project import _build_planning_context

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
		self.assertEqual(workflow.adapter_key, "minimax_h3")
		self.assertFalse(frappe.db.exists("DocType", "AI Model Profile"))


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
	if media_type == "Video":
		# Avoid ffprobe in this relation-only fixture.
		with patch.object(version, "set_file_metadata"):
			version.insert(ignore_permissions=True)
	else:
		version.insert(ignore_permissions=True)
	return asset, version


def _ensure_workflow():
	workflow = frappe.get_doc({
		"doctype": "Generation Workflow",
		"workflow_key": f"product_showcase_{frappe.generate_hash(length=5)}",
		"adapter_key": "minimax_h3",
		"workflow_json": (
			'{"load_img":{"inputs":{"image":""},"class_type":"VHS_LoadImagePath"},'
			'"minimax_cond":{"inputs":{"length":124},"class_type":"MiniMaxH3ImageToVideo"},'
			'"save_video":{"inputs":{"images":["dec_video",0],"frame_rate":24,'
			'"filename_prefix":"JoyMedia","loop_count":0,"format":"video/h264-mp4",'
			'"pingpong":false,"save_output":true},"class_type":"VHS_VideoCombine"}}'
		),
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
