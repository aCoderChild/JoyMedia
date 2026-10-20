import json
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.project import versions


def project(label="Version test"):
	return frappe.get_doc(
		{
			"doctype": "Media Project",
			"project_name": label,
			"product_name": "One product",
			"video_idea": "A short product film.",
		}
	).insert(ignore_permissions=True)


class TestProjectVersions(FrappeTestCase):
	def test_explicit_grouping_preserves_projects_and_status(self):
		root, edit = project(), project("Alternate")
		before = edit.as_dict()
		versions.organize_edits(
			root.name, [{"project": edit.name, "label": "Warm light", "kind": "Experiment"}]
		)
		edit.reload()
		self.assertEqual(
			(edit.version_of, edit.version_label, edit.status), (root.name, "Warm light", before["status"])
		)
		self.assertEqual(edit.video_idea, before["video_idea"])
		self.assertEqual(
			{row["name"] for row in versions.get_history(root.name)["items"]}, {root.name, edit.name}
		)

	def test_other_owner_cannot_be_grouped_even_by_admin(self):
		root, edit = project(), project()
		frappe.db.set_value("Media Project", edit.name, "owner", "foreign@example.com")
		with self.assertRaises(frappe.ValidationError):
			versions.organize_edits(root.name, [{"project": edit.name, "label": "Other"}])
		self.assertFalse(frappe.db.get_value("Media Project", edit.name, "version_of"))

	def test_validation_rejects_entire_mixed_group_before_writing(self):
		root, good, bad = project(), project(), project()
		with self.assertRaises(frappe.ValidationError):
			versions.organize_edits(
				root.name, [{"project": good.name, "label": "Good"}, {"project": bad.name, "label": ""}]
			)
		self.assertFalse(frappe.db.get_value("Media Project", good.name, "version_of"))

	def test_nested_and_cyclic_membership_are_rejected(self):
		root, edit = project(), project()
		versions.organize_edits(root.name, [{"project": edit.name, "label": "Edit"}])
		root.version_of = edit.name
		with self.assertRaises(frappe.ValidationError):
			root.save(ignore_permissions=True)

	def test_working_edit_compare_and_swap_rejects_stale_tab(self):
		root, edit = project(), project()
		versions.organize_edits(root.name, [{"project": edit.name, "label": "Edit"}])
		versions.set_working_edit(root.name, edit.name, root.name)
		self.assertEqual(versions.get_history(root.name)["items"][0]["name"], edit.name)
		with self.assertRaises(frappe.ValidationError):
			versions.set_working_edit(root.name, root.name, root.name)
		self.assertEqual(frappe.db.get_value("Media Project", root.name, "current_edit"), edit.name)

	def test_unrelated_project_cannot_be_selected(self):
		root, other = project(), project()
		with self.assertRaises(frappe.ValidationError):
			versions.set_working_edit(root.name, other.name, root.name)

	def test_history_enforces_owner_before_reading_media(self):
		root = project()
		user = frappe.session.user
		try:
			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				versions.get_history(root.name, kind="exports")
		finally:
			frappe.set_user(user)

	def test_edit_copy_preserves_exact_edl_and_baseline_without_gpu_jobs(self):
		from joymedia.joymedia.doctype.media_project.test_media_project import _ensure_workflow

		root = project()
		root.db_set({"workflow": _ensure_workflow(), "total_duration_seconds": 2})
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "baseline.mp4"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-f",
					"lavfi",
					"-i",
					"color=c=blue:s=64x64:r=24:d=2",
					"-c:v",
					"libx264",
					"-pix_fmt",
					"yuv420p",
					str(path),
				],
				check=True,
			)
			file = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"version-test-{frappe.generate_hash(length=10)}.mp4",
					"content": path.read_bytes(),
					"is_private": 1,
				}
			).insert(ignore_permissions=True)
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": "Baseline",
				"media_type": "Video",
				"asset_scope": "Project Output",
				"asset_category": "Other",
				"media_project": root.name,
			}
		).insert(ignore_permissions=True)
		base = frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": asset.name,
				"file": file.file_url,
				"source": "Generated",
			}
		).insert(ignore_permissions=True)
		shots = []
		for number in (1, 2):
			shot = frappe.get_doc(
				{
					"doctype": "Shot",
					"media_project": root.name,
					"shot_number": number,
					"duration_seconds": 1,
					"generation_prompt": "The subject waits.",
				}
			).insert(ignore_permissions=True)
			shot.db_set("selected_output_asset_version", base.name, update_modified=False)
			shots.append(shot)
		clips = []
		for i, shot in enumerate(shots):
			clips.append(
				frappe.get_doc(
					{
						"doctype": "Timeline Clip",
						"media_project": root.name,
						"shot": shot.name,
						"clip_order": i + 1,
						"track_type": "Video",
						"track_index": 0,
						"timeline_start_frame": i * 24,
						"source_asset_version": base.name,
						"source_in_frame": 0,
						"source_out_frame": 24,
						"initial_source_in_frame": 0,
						"initial_source_out_frame": 24,
						"enabled": 1,
						"transition_to_next": "Cut",
					}
				).insert(ignore_permissions=True)
			)
		frappe.db.set_value(
			"Timeline Clip",
			clips[0].name,
			{
				"source_in_frame": 3,
				"source_out_frame": 19,
				"transition_to_next": "Dissolve",
				"transition_frames": 3,
				"timeline_start_frame": 12,
			},
			update_modified=False,
		)
		frappe.db.set_value(
			"Timeline Clip",
			clips[1].name,
			{"source_in_frame": 2, "source_out_frame": 18, "timeline_start_frame": 25},
			update_modified=False,
		)
		audio = frappe.get_doc(
			{
				"doctype": "Timeline Clip",
				"media_project": root.name,
				"shot": shots[1].name,
				"clip_order": 2,
				"track_type": "Audio",
				"track_index": 1,
				"timeline_start_frame": 25,
				"source_asset_version": base.name,
				"source_in_frame": 2,
				"source_out_frame": 18,
				"enabled": 1,
				"audio_role": "Source",
				"linked_video_clip": clips[1].name,
				"gain_db": -7,
				"transition_to_next": "Cut",
			}
		).insert(ignore_permissions=True)
		before = frappe.db.count("Generation Run")
		result = versions.create_edit(root.name, "Alternate lighting", make_working=False)
		copy = frappe.get_doc("Media Project", result["edit"])
		old_times = frappe.get_all(
			"Shot",
			filters={"media_project": root.name},
			fields=["duration_seconds", "planned_frame_count"],
			order_by="shot_number",
		)
		new_times = frappe.get_all(
			"Shot",
			filters={"media_project": copy.name},
			fields=["duration_seconds", "planned_frame_count"],
			order_by="shot_number",
		)
		self.assertEqual(old_times, new_times)

		self.assertEqual(frappe.db.count("Generation Run"), before)
		self.assertFalse(copy.current_output_asset_version)
		from joymedia.services.editing.post_production import _edited_by_hand

		self.assertTrue(copy.finished_timeline_signature)
		self.assertTrue(
			_edited_by_hand(copy.name)
		)  # copied mutes, trims and soundtrack must survive regeneration
		self.assertFalse(frappe.db.get_value("Media Project", root.name, "current_edit"))
		copied = frappe.get_all(
			"Timeline Clip",
			filters={"media_project": copy.name},
			fields=[
				"name",
				"track_type",
				"clip_order",
				"source_in_frame",
				"source_out_frame",
				"timeline_start_frame",
				"transition_to_next",
				"transition_frames",
				"linked_video_clip",
				"gain_db",
			],
			order_by="track_type desc, clip_order asc",
		)
		videos = sorted([r for r in copied if r.track_type == "Video"], key=lambda r: r.clip_order)
		self.assertEqual(
			[
				(
					r.source_in_frame,
					r.source_out_frame,
					r.timeline_start_frame,
					r.transition_to_next,
					r.transition_frames,
				)
				for r in videos
			],
			[(3, 19, 12, "Dissolve", 3), (2, 18, 25, "Cut", 0)],
		)
		copied_audio = next(r for r in copied if r.track_type == "Audio")
		self.assertEqual((copied_audio.linked_video_clip, copied_audio.gain_db), (videos[1].name, -7))
		for s in frappe.get_all(
			"Shot",
			filters={"media_project": copy.name},
			fields=["selected_output_asset_version", "brand_approval_signature"],
		):
			v = frappe.get_doc("Asset Version", s.selected_output_asset_version)
			self.assertEqual(
				(v.derived_from, v.file, v.content_hash), (base.name, base.file, base.content_hash)
			)
			self.assertFalse(s.brand_approval_signature)
		self.assertTrue(audio.name)
		final_asset = frappe.copy_doc(asset)
		final_asset.asset_name = f"{root.name} Final Video"
		final_asset.insert(ignore_permissions=True)
		final = frappe.copy_doc(base)
		final.media_asset, final.source = final_asset.name, "Edited"
		final.edit_manifest_json = versions.export_manifest(root, [], "snapshot")
		final.insert(ignore_permissions=True)
		exports = versions.get_history(copy.name, kind="exports")
		self.assertEqual([item.name for item in exports["items"]], [final.name])
		self.assertEqual(exports["items"][0]["purpose"], "review")
		self.assertTrue(exports["items"][0]["has_edit_snapshot"])
		takes = versions.get_history(root.name, kind="takes", page_length=1)
		self.assertEqual(len(takes["items"]), 1)
		self.assertTrue(takes["has_more"])
		self.assertTrue(takes["items"][0]["is_selected"])
		selected_shot = takes["items"][0]["shot"]
		filtered = versions.get_history(root.name, kind="takes", shot_name=selected_shot, page_length=1)
		self.assertEqual([row["shot"] for row in filtered["items"]], [selected_shot])
		self.assertFalse(filtered["has_more"])
		self.assertIn(selected_shot, {row["name"] for row in filtered["scenes"]})
		self.assertEqual(
			versions.get_history(root.name, kind="takes", shot_name=selected_shot, start=1)["items"], []
		)
		foreign = project("Unrelated scene history")
		with self.assertRaises(frappe.ValidationError):
			versions.get_history(foreign.name, kind="takes", shot_name=selected_shot)
		with self.assertRaises(frappe.ValidationError):
			final.edit_manifest_json = "{}"
			final.save(ignore_permissions=True)

	def test_export_snapshot_is_immutable(self):
		from joymedia.joymedia.doctype.asset_version.asset_version import AssetVersion

		self.assertIn("edit_manifest_json", AssetVersion.IMMUTABLE_FIELDS)
		root = project()
		payload = json.loads(
			versions.export_manifest(
				root,
				[{"source_asset_version": "IMMUTABLE", "source_in_frame": 2, "source_out_frame": 12}],
				"sig",
			)
		)
		self.assertEqual(payload["timeline_signature"], "sig")
		self.assertEqual(payload["clips"][0]["source_asset_version"], "IMMUTABLE")

	def test_archived_family_is_readable_but_not_editable_until_restored(self):
		from joymedia.api.projects import archive_project, restore_project

		root, edit = project(), project()
		versions.organize_edits(root.name, [{"project": edit.name, "label": "Alternate"}])
		archive_project(root.name)
		self.assertEqual(len(versions.get_history(edit.name)["items"]), 2)
		edit.reload()
		with self.assertRaises(frappe.ValidationError):
			edit._require_write_access()
		restore_project(root.name)
		edit._require_write_access()

	def test_edit_owned_controls_and_source_patches_are_copied_with_lineage(self):
		from joymedia.services.consistency.repair import _project_asset_path

		root = project("Control copy regression")
		result = versions.create_edit(root.name, "Source controls", make_working=False)
		target = frappe.get_doc("Media Project", result["edit"])

		def image(label, evidence=None):
			import io

			from PIL import Image

			data = io.BytesIO()
			Image.new("RGB", (10, 10), "white").save(data, "PNG")
			asset = frappe.get_doc(
				dict(
					doctype="Media Asset",
					asset_name=label,
					media_project=root.name,
					asset_scope="Project Output",
					asset_category="Other",
					media_type="Image",
				)
			).insert(ignore_permissions=True)
			file = frappe.get_doc(
				dict(
					doctype="File",
					file_name=label + ".png",
					content=data.getvalue(),
					is_private=1,
					attached_to_doctype="Media Asset",
					attached_to_name=asset.name,
				)
			).insert(ignore_permissions=True)
			return frappe.get_doc(
				dict(
					doctype="Asset Version",
					media_asset=asset.name,
					file=file.file_url,
					source="Uploaded",
					preservation_evidence_json=json.dumps(evidence) if evidence else None,
				)
			).insert(ignore_permissions=True)

		source_version = image("product")
		patch_version = image("patch")
		frame = image(
			"frame",
			dict(
				product_lock=dict(
					canvas=[100, 100],
					items=[
						dict(
							box=[0, 0, 10, 10],
							file=patch_version.file,
							patch_asset_version=patch_version.name,
							source_asset_version=source_version.name,
						)
					],
				)
			),
		)
		copied = {}
		new = versions.copy_control_reference(frame.name, root, target, copied)
		clone = frappe.get_doc("Asset Version", new)
		self.assertEqual(frame.name, clone.derived_from)
		self.assertEqual(frame.file, clone.file)
		self.assertEqual(new, versions.copy_control_reference(frame.name, root, target, copied))
		new_patch = json.loads(clone.preservation_evidence_json)["product_lock"]["items"][0][
			"patch_asset_version"
		]
		new_source = json.loads(clone.preservation_evidence_json)["product_lock"]["items"][0][
			"source_asset_version"
		]
		self.assertEqual(copied[source_version.name], new_source)
		self.assertNotEqual(source_version.name, new_source)
		self.assertNotEqual(patch_version.name, new_patch)
		self.assertEqual(patch_version.name, frappe.get_doc("Asset Version", new_patch).derived_from)
		_project_asset_path(target, new)
		_project_asset_path(target, new_patch)
		_project_asset_path(target, new_source)
		with self.assertRaises(frappe.PermissionError):
			_project_asset_path(target, frame.name)
