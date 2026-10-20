import contextlib
import importlib.util
import io
import json
import os
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe


def module():
	path = Path(frappe.get_app_path("joymedia")).parent / "scripts" / "prune_comfy_uploads.py"
	spec = importlib.util.spec_from_file_location("retention", path)
	value = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(value)
	return value


class TestUploadRetention(TestCase):
	def test_only_stale_unprotected_regular_cache_copies_are_removed(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			names = [f"joymedia_{letter * 32}.png" for letter in "abcd"]
			for name in names[:3]:
				(root / name).write_bytes(b"cached copy")
				os.utime(root / name, (time.time() - 7200,) * 2)
			os.utime(root / names[2], None)
			(root / names[3]).symlink_to(root / names[1])
			queue = {"queue_running": [{"image": names[1]}]}
			request = dict(directory=folder, names=names, queue_url="http://local/queue", hours=1, max_bytes=1000, apply=True)
			responses = [io.BytesIO(json.dumps(queue).encode()), io.BytesIO(json.dumps(queue).encode())]
			with patch("sys.stdin", io.StringIO(json.dumps(request))), patch("urllib.request.urlopen", side_effect=responses), contextlib.redirect_stdout(io.StringIO()):
				exec(module().REMOTE, {})
			self.assertFalse((root / names[0]).exists())
			self.assertTrue(all((root / name).exists() for name in names[1:]))

	def test_new_queue_reference_between_inventory_and_delete_is_protected(self):
		with tempfile.TemporaryDirectory() as folder:
			name = "joymedia_" + "e" * 32 + ".mp4"
			path = Path(folder) / name
			path.write_bytes(b"cached copy")
			os.utime(path, (time.time() - 7200,) * 2)
			request = dict(directory=folder, names=[name], queue_url="http://local/queue", hours=1, max_bytes=1000, apply=True)
			responses = [io.BytesIO(b"{}"), io.BytesIO(json.dumps({"queue_pending": [{"video": name}]}).encode())]
			with patch("sys.stdin", io.StringIO(json.dumps(request))), patch("urllib.request.urlopen", side_effect=responses), contextlib.redirect_stdout(io.StringIO()):
				exec(module().REMOTE, {})
			self.assertTrue(path.exists())

	def test_unsafe_names_are_rejected_before_deletion(self):
		with tempfile.TemporaryDirectory() as folder:
			request = dict(directory=folder, names=["../source.mp4"], queue_url="http://local/queue", hours=1, max_bytes=1000, apply=True)
			with patch("sys.stdin", io.StringIO(json.dumps(request))), patch("urllib.request.urlopen", return_value=io.BytesIO(b"{}")), self.assertRaises(ValueError):
				exec(module().REMOTE, {})
