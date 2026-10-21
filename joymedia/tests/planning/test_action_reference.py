import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.services.intake.action_reference import annotate_reference


class TestActionReferenceAnnotations(TestCase):
	def test_source_bound_annotations_keep_machine_evidence_and_never_qualify_physics(self):
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "reference.mp4"
			path.write_bytes(b"immutable reference fixture")
			digest = hashlib.sha256(path.read_bytes()).hexdigest()
			machine = [{"start": 0, "end": 2, "caption": "Original machine observation"}]
			version = frappe._dict(
				name="version",
				media_asset="asset",
				file="/reference.mp4",
				analysis_json=json.dumps(
					{"action_reference": {"version": 2, "source_sha256": digest, "clips": machine}}
				),
			)
			asset = SimpleNamespace(check_permission=Mock())

			def document(doctype, *args, **kwargs):
				return asset if doctype == "Media Asset" else SimpleNamespace(get_full_path=lambda: str(path))

			with (
				patch(
					"joymedia.services.intake.cinematography.motion_references",
					side_effect=lambda *a, **k: iter([version]),
				),
				patch.object(frappe, "get_doc", side_effect=document),
				patch(
					"joymedia.vendor.camerapath.video.ffprobe.probe_video",
					return_value=SimpleNamespace(duration_seconds=4),
				),
				patch.object(frappe.db, "set_value") as write,
			):
				clips = [
					{"start": 1, "end": 3, "caption": "The actor presses the material against the surface."}
				]
				result = annotate_reference(
					{}, "version", digest, clips, "Sampled observations, not measured physics."
				)
				stored = json.loads(write.call_args.args[3])["action_reference"]
				self.assertEqual(machine, stored["machine_clips"])
				self.assertEqual(digest, stored["annotation"]["source_sha256"])
				self.assertFalse(result["physical_qualification"])
				self.assertFalse(stored["annotation"]["physical_qualification"])
				asset.check_permission.assert_called_with("write")
				write.reset_mock()
				with self.assertRaisesRegex(ValueError, "changed"):
					annotate_reference({}, "version", "incorrect-hash", clips)
				write.assert_not_called()
				with self.assertRaisesRegex(ValueError, "within"):
					annotate_reference(
						{}, "version", digest, [{"start": 3, "end": 5, "caption": "Outside the source."}]
					)
				write.assert_not_called()
