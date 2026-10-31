"""Selected demo restore protections; all records and copied files are rolled back."""

from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.demo import seed


class TestDemoSeed(TestCase):
	def setUp(self):
		self.manifest, self.rows = seed.read_bundle()
		if any(frappe.db.exists(row["doctype"], row["name"]) for row in self.rows):
			self.skipTest("Use a test site without the selected handover dataset")
		self.user = frappe.session.user
		frappe.set_user("Administrator")
		self.addCleanup(lambda: frappe.set_user(self.user))
		self.addCleanup(frappe.db.rollback)
		self.config = patch.dict(frappe.conf, {"joymedia_allow_demo_data": True})
		self.config.start()
		self.addCleanup(self.config.stop)
		self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("No AI calls"))
		self.network.start()
		self.addCleanup(self.network.stop)

	def test_restore_shelves_workspace_and_timeline(self):
		from joymedia.api.projects import get_project_workspace
		from joymedia.services.project.versions import get_videos

		result = seed.load()
		self.assertEqual(result["created"], len(self.rows))
		for root, expected in (("02501", {"02558", "02586"}), ("02559", {"02563"})):
			videos = get_videos(f"JM-DEMO-PRJ-{root}")["videos"]
			self.assertEqual({v["name"] for v in videos}, {f"JM-DEMO-PRJ-{n}" for n in expected})
			self.assertTrue(all(v["video"].startswith("/private/files/jm-demo-") for v in videos))
			for video in videos:
				workspace = get_project_workspace(video["name"])
				self.assertTrue(workspace["storyboard"])
		for row in self.rows:
			if row["doctype"] == "Timeline Clip":
				doc = frappe.get_doc(row["doctype"], row["name"])
				for key in (
					"source_in_frame",
					"source_out_frame",
					"timeline_start_frame",
					"source_asset_version",
				):
					self.assertEqual(doc.get(key), row.get(key))
		for row in self.rows:
			if row["doctype"] == "Shot":
				frappe.get_doc("Shot", row["name"]).validate_selected_output_asset_version()

	def test_repeat_preserves_edits(self):
		seed.load()
		name = "JM-DEMO-PRJ-02501"
		frappe.db.set_value("Media Project", name, "project_name", "Edited demo")
		self.assertEqual(seed.load()["skipped"], len(self.rows))
		self.assertEqual(frappe.db.get_value("Media Project", name, "project_name"), "Edited demo")

	def test_disabled_flag_refuses_import(self):
		with patch.dict(frappe.conf, {"joymedia_allow_demo_data": "0"}):
			with self.assertRaises(frappe.ValidationError):
				seed.load()

	def test_guest_cannot_import(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			seed.load()

	def test_conflicting_owner_is_rejected(self):
		seed.load()
		frappe.db.set_value("Media Project", "JM-DEMO-PRJ-02501", "owner", "Guest")
		with self.assertRaises(frappe.ValidationError):
			seed.load()

	def test_failed_restore_rolls_back_records_and_files(self):
		get_doc = frappe.get_doc

		def fail_on_shot(*args, **kwargs):
			if args and isinstance(args[0], dict) and args[0].get("doctype") == "Shot":
				raise ValueError("simulated restore failure")
			return get_doc(*args, **kwargs)

		paths = seed.media_paths(self.manifest)
		absent = [target for _, target in paths if not target.exists()]
		with patch.object(frappe, "get_doc", side_effect=fail_on_shot):
			with self.assertRaisesRegex(ValueError, "simulated restore failure"):
				seed.load()
		self.assertFalse(frappe.db.exists("Media Project", "JM-DEMO-PRJ-02501"))
		self.assertTrue(all(not target.exists() for target in absent))

	def test_unresolved_link_is_rejected_before_restore(self):
		rows = [dict(row) for row in self.rows]
		next(row for row in rows if row["doctype"] == "Shot")["media_project"] = "MISSING"
		with self.assertRaisesRegex(ValueError, "Unresolved demo link"):
			seed.validate_bundle(rows, self.manifest)

	def test_media_hash_mismatch_is_rejected(self):
		manifest = {**self.manifest, "media": [dict(self.manifest["media"][0], sha256="0" * 64)]}
		with self.assertRaisesRegex(ValueError, "checksum mismatch"):
			seed.media_paths(manifest)
