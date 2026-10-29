import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from joymedia.services.planning.product_views import _generate_candidate, _prepared_view_result
from joymedia.services.planning.reference_bridges import (
	frame_provenance,
	record_sample,
	retain_storyboard_bridge,
	sample_bridge,
)


class TestReferenceBridges(TestCase):
	def test_storyboard_clip_is_private_intermediate_evidence_never_a_selectable_take(self):
		attempt = frappe._dict(name="attempt", generation_task="task", comfyui_endpoint_url="endpoint")
		workflow = frappe._dict(
			execution_spec=json.dumps(
				{"outputs": {"preparation_bridge": {"node_key": "92", "frame_index": 68}}}
			)
		)
		created = []

		def document(dt, name=None):
			if dt == "Generation Task":
				return frappe._dict(generation_run="run")
			created.append(dt)
			doc = MagicMock()
			doc.insert.return_value = doc
			doc.file_url = "/private/bridge.mp4"
			return doc

		with (
			patch("frappe.db.exists", side_effect=[False, True]),
			patch("frappe.db.get_value", return_value="project"),
			patch("frappe.get_doc", side_effect=document),
			patch("joymedia.services.workflows.comfyui.download_output", return_value=b"clip") as download,
		):
			for _ in range(2):
				retain_storyboard_bridge(
					attempt, workflow, {"outputs": {"92": {"videos": [{"filename": "bridge.mp4"}]}}}
				)
			download.assert_called_once()
		self.assertEqual(["File", "Generation Artifact"], [d["doctype"] for d in created])
		self.assertEqual(1, created[0]["is_private"])
		self.assertEqual("project", created[0]["attached_to_name"])
		self.assertEqual("Intermediate", created[1]["artifact_role"])
		self.assertEqual(68, json.loads(created[1]["provider_locator"])["frame"])

	def test_h3_product_preparation_does_not_require_an_image_fallback_workflow(self):
		with (
			patch.dict(frappe.conf, {"joymedia_product_view_workflow": None}),
			patch("frappe.db.get_value", return_value="/original.png"),
			patch("frappe.get_doc") as file,
			patch(
				"joymedia.services.planning.product_views.original_reference",
				return_value={"file": "/original.png"},
			),
			patch(
				"joymedia.services.keyframes.locations._keyframe_workflow",
				side_effect=ValueError("No image workflow"),
			) as fallback,
			patch(
				"joymedia.services.planning.reference_bridges.product_view_from_h3",
				return_value=b"qualified frame",
			) as h3,
		):
			file.return_value.get_full_path.return_value = "/original.png"
			self.assertEqual(
				b"qualified frame",
				_generate_candidate(
					frappe._dict(name="project"), frappe._dict(asset_version="original"), "side"
				),
			)
			self.assertTrue(callable(h3.call_args.args[3]))
			fallback.assert_not_called()

	def test_samples_are_real_frames_with_clip_timestamp_and_only_qualified_frame_lineage(self):
		with tempfile.TemporaryDirectory() as directory:
			folder = Path(directory)
			video = folder / "source.mp4"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-f",
					"lavfi",
					"-i",
					"color=c=blue:s=96x96:r=24",
					"-t",
					"0.5",
					"-c:v",
					"libx264",
					str(video),
				],
				check=True,
			)
			bridge = {
				"path": str(video),
				"folder": folder,
				"report": {
					"project": "project",
					"file": "/private/bridge.mp4",
					"clip_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
					"workflow": "H3",
					"workflow_hash": "workflow-hash",
					"samples": [],
				},
			}
			samples = list(sample_bridge(bridge))
			self.assertEqual(6, len(samples))
			self.assertTrue(all(content.startswith(b"\x89PNG") for content, second in samples))
			with patch("frappe.get_site_path", side_effect=lambda *parts: str(folder.joinpath(*parts))):
				first, second = samples[0]
				record_sample(bridge, first, second, False)
				self.assertIsNone(frame_provenance(frappe._dict(name="project"), first))
				record_sample(bridge, first, second, True)
				proof = frame_provenance(frappe._dict(name="project"), first)
				self.assertEqual(second, proof["timestamp"])
				self.assertEqual(hashlib.sha256(first).hexdigest(), proof["frame_sha256"])
				self.assertEqual("workflow-hash", proof["workflow_hash"])
				self.assertEqual(2, len(json.loads((folder / "manifest.json").read_text())["samples"]))

	def test_qualified_generated_angle_does_not_override_strict_source_art(self):
		preview = _prepared_view_result("original", "back", "generated", True)
		self.assertEqual("source_locked", preview["status"])
		self.assertEqual("original", preview["fallback"])
		self.assertEqual("generated", preview["candidate"])
		self.assertEqual("ready", _prepared_view_result("original", "back", "generated", False)["status"])
