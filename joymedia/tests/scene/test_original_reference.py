import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.project.reference_lineage import original_reference


class TestOriginalReference(TestCase):
	def test_generated_pose_and_cutout_resolve_to_unchanged_original_bytes(self):
		with tempfile.TemporaryDirectory() as folder:
			path = Path(folder) / "original.png"
			path.write_bytes(b"original identity image")
			checksum = hashlib.sha256(path.read_bytes()).hexdigest()
			versions = {
				"original": {"file": "/private/original.png", "content_hash": checksum},
				"pose": {"analysis_json": json.dumps({"source_asset_version": "original"})},
				"cutout": {"analysis_json": json.dumps({"subject_cutout": {"source_asset_version": "pose"}})},
				"copy": {"derived_from": "cutout"},
			}

			def lookup(doctype, name, fields, **kwargs):
				return frappe._dict(name=name, **versions[name]) if name in versions else None

			with (
				patch.object(frappe.db, "get_value", side_effect=lookup),
				patch("frappe.get_doc", return_value=SimpleNamespace(get_full_path=lambda: str(path))),
			):
				for version in versions:
					self.assertEqual(
						{
							"asset_version": "original",
							"file": "/private/original.png",
							"content_hash": checksum,
						},
						original_reference(version),
					)
				path.write_bytes(b"altered original")
				with self.assertRaisesRegex(ValueError, "bytes changed"):
					original_reference("copy")

	def test_broken_cyclic_and_excessive_lineage_cannot_become_an_identity(self):
		for versions, start, message in (
			({}, "missing", "unavailable"),
			({"A": {"source_asset_version": "A"}}, "A", "cycle"),
			({"A": {"source_asset_version": "B"}, "B": {"source_asset_version": "A"}}, "A", "cycle"),
			({str(i): {"source_asset_version": str(i + 1)} for i in range(20)}, "0", "depth"),
			({"A": []}, "A", "metadata must be an object"),
			({"A": {}}, "A", "immutable image evidence"),
		):
			with (
				self.subTest(message=message),
				patch.object(
					frappe.db,
					"get_value",
					side_effect=lambda dt, name, fields, **kwargs: frappe._dict(
						name=name, analysis_json=json.dumps(versions[name])
					)
					if name in versions
					else None,
				),
			):
				with self.assertRaisesRegex(ValueError, message):
					original_reference(start)
