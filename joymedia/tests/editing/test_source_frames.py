import json
import unittest
from unittest.mock import patch

import frappe

from joymedia.services.editing.composer import product_lock_for


class TestAuthoredFrameLock(unittest.TestCase):
	def test_only_the_exact_immutable_source_patch_can_protect_the_take(self):
		lock = {
			"canvas": [720, 1280],
			"items": [
				{
					"patch_asset_version": "PATCH",
					"file": "/private/files/patch.png",
					"source_asset_version": "SOURCE",
				}
			],
		}
		snapshot = json.dumps(
			{
				"media_project": "P",
				"shots": [
					{"shot": "S", "references": [{"reference_role": "first_frame", "asset_version": "FRAME"}]}
				],
			}
		)

		def doc(kind, name):
			return (
				frappe._dict(preservation_evidence_json=json.dumps({"product_lock": lock}))
				if kind == "Asset Version"
				else frappe._dict(name="P")
			)

		def value(kind, *args, **kwargs):
			return snapshot if kind == "Generation Run" else "/private/files/patch.png"

		with (
			patch("joymedia.services.editing.composer.frappe.db.get_value", side_effect=value),
			patch("joymedia.services.editing.composer.frappe.get_doc", side_effect=doc),
			patch("joymedia.services.consistency.repair._project_asset_path") as checked,
		):
			self.assertEqual(product_lock_for("R", "S", []), lock)
			self.assertEqual([call.args[1] for call in checked.call_args_list], ["FRAME", "PATCH"])
		with (
			patch(
				"joymedia.services.editing.composer.frappe.db.get_value",
				side_effect=lambda kind, *a, **k: snapshot
				if kind == "Generation Run"
				else "/private/files/different.png",
			),
			patch("joymedia.services.editing.composer.frappe.get_doc", side_effect=doc),
			patch("joymedia.services.consistency.repair._project_asset_path"),
		):
			with self.assertRaisesRegex(ValueError, "does not match"):
				product_lock_for("R", "S", [])

	def test_closing_hold_uses_the_frozen_authored_frame(self):
		from joymedia.services.editing.composer import _closing_hold_source

		snapshot = json.dumps(
			{
				"media_project": "P",
				"shots": [
					{
						"shot": "S",
						"closing_hold_seconds": 5,
						"references": [{"reference_role": "first_frame", "asset_version": "FRAME"}],
					}
				],
			}
		)
		with (
			patch("joymedia.services.editing.composer.frappe.db.get_value", return_value=snapshot),
			patch("joymedia.services.editing.composer.frappe.get_doc", return_value=frappe._dict(name="P")),
			patch(
				"joymedia.services.consistency.repair._project_asset_path", return_value="/frozen/frame.png"
			) as checked,
		):
			self.assertEqual(_closing_hold_source("R", "S"), (5, "/frozen/frame.png"))
			self.assertEqual(checked.call_args.args[1], "FRAME")

	def test_a_new_image_dependency_wins_over_the_old_snapshot_frame(self):
		from pathlib import Path
		from tempfile import TemporaryDirectory

		from joymedia.services.editing.composer import _closing_hold_source

		for role in ("Primary Image", "Last Frame"):
			with self.subTest(role=role), TemporaryDirectory() as folder:
				path = Path(folder) / "actual-frame.png"
				path.write_bytes(b"actual immutable image")
				snapshot = json.dumps(
					{"shots": [{"shot": "S", "closing_hold_seconds": 2, "keyframe_artifact": "OLD"}]}
				)

				def value(kind, name, *args, **kwargs):
					if kind == "Generation Run":
						return snapshot
					if kind == "Generation Workflow":
						return "Video"
					if kind == "Generation Attempt":
						return "A-NEW"
					if isinstance(name, dict):
						self.assertEqual(name["artifact_role"], role)
						return "NEW"
					self.assertEqual(name, "NEW")
					return "/private/files/new.png"

				with (
					patch("joymedia.services.editing.composer.frappe.db.get_value", side_effect=value),
					patch(
						"joymedia.services.editing.composer.frappe.get_all",
						return_value=[
							frappe._dict(
								name="VIDEO",
								workflow="W",
								depends_on_task="IMAGE",
								dependency_artifact_role=role,
							)
						],
					),
					patch(
						"joymedia.services.editing.composer.frappe.get_doc",
						return_value=frappe._dict(get_full_path=lambda: str(path)),
					),
				):
					self.assertEqual(_closing_hold_source("R", "S"), (2, str(path)))

	def test_an_incomplete_new_dependency_never_falls_back_to_the_old_picture(self):
		from joymedia.services.editing.composer import _closing_hold_source

		snapshot = json.dumps(
			{"shots": [{"shot": "S", "closing_hold_seconds": 2, "keyframe_artifact": "OLD"}]}
		)
		with (
			patch(
				"joymedia.services.editing.composer.frappe.db.get_value",
				side_effect=[snapshot, "Video", None],
			),
			patch(
				"joymedia.services.editing.composer.frappe.get_all",
				return_value=[
					frappe._dict(
						name="VIDEO",
						workflow="W",
						depends_on_task="IMAGE",
						dependency_artifact_role="Primary Image",
					)
				],
			),
		):
			with self.assertRaisesRegex(ValueError, "no completed artifact"):
				_closing_hold_source("R", "S")

	def test_static_actor_presentation_requires_an_authored_frame_and_no_action(self):
		from joymedia.services.consistency.retention import is_static_presentation

		plan = {
			"camera_motion": "locked",
			"scene_contract": {
				"version": 1,
				"entities": [{"id": "subject", "label": "the reference subject"}],
				"events": [],
				"properties": [{"entity": "subject", "name": "motion", "value": "stationary"}],
			},
		}
		scene = {
			"duration_seconds": 4,
			"references": [{"reference_role": "Character", "asset_version": "ACTOR"}],
			"motion_plan_json": plan,
		}
		self.assertFalse(is_static_presentation(scene))
		scene["references"].append({"reference_role": "first_frame", "asset_version": "FRAME"})
		self.assertTrue(is_static_presentation(scene))
		plan["camera_motion"] = "pan"
		self.assertFalse(is_static_presentation(scene))
