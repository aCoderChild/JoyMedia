from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from joymedia.api.projects import archive_project, delete_project_forever, get_project_cards, restore_project
from joymedia.services.project import trash
from joymedia.tests.project.test_versions import project


def asset(owner_project=None, label="Pack shot"):
	media = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": label,
			"media_type": "Image",
			"asset_category": "Product",
			"asset_scope": "Library",
			"status": "Active",
			"media_project": owner_project,
		}
	)
	media.db_insert()
	version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": media.name,
			"version_number": 1,
			"file": f"/private/files/{frappe.generate_hash(length=8)}.png",
			"source": "Generated",
		}
	)
	version.db_insert()
	return media.name, version.name


def shot(project_name):
	doc = frappe.get_doc(
		{
			"doctype": "Shot",
			"media_project": project_name,
			"shot_number": 1,
			"duration_seconds": 4,
			"generation_prompt": "The pack on a table.",
		}
	)
	doc.db_insert()
	return doc.name


class TestTrash(FrappeTestCase):
	def family(self):
		root, video = project("Trash root"), project("Trash video")
		video.db_set({"version_of": root.name, "version_label": "Video 2 · Morning tissue"})
		return root, video

	def test_deleting_a_video_keeps_the_project_library_and_shared_pictures(self):
		root, video = self.family()
		library = asset(label="Uploaded pack")
		shared = asset(video.name, "Shared drawing")
		own = asset(video.name, "Own drawing")
		frappe.get_doc(
			{
				"doctype": "Project Reference",
				"parent": root.name,
				"parenttype": "Media Project",
				"parentfield": "selected_media",
				"asset_version": shared[1],
			}
		).db_insert()
		scene = shot(video.name)
		archive_project(video.name)
		self.assertEqual(trash.RETENTION_DAYS, trash.days_left(now_datetime()))
		listed = get_project_cards(status="Archived", page_length=100)["items"]
		card = next(row for row in listed if row["name"] == video.name)
		self.assertEqual(("Morning tissue", "Trash root"), (card["project_name"], card["in_project"]))

		delete_project_forever(video.name)
		self.assertFalse(frappe.db.exists("Media Project", video.name))
		self.assertFalse(frappe.db.exists("Shot", scene))
		self.assertFalse(frappe.db.exists("Asset Version", own[1]))
		self.assertFalse(frappe.db.exists("Media Asset", own[0]))
		self.assertTrue(frappe.db.exists("Media Project", root.name))
		self.assertTrue(frappe.db.exists("Asset Version", library[1]))
		self.assertTrue(frappe.db.exists("Asset Version", shared[1]))
		self.assertIsNone(frappe.db.get_value("Media Asset", shared[0], "media_project"))

	def test_only_trashed_projects_can_be_deleted_and_restore_clears_the_date(self):
		root, _video = self.family()
		with self.assertRaises(frappe.ValidationError):
			delete_project_forever(root.name)
		archive_project(root.name)
		self.assertTrue(frappe.db.get_value("Media Project", root.name, "archived_on"))
		restore_project(root.name)
		self.assertEqual(
			("Draft", None), frappe.db.get_value("Media Project", root.name, ["status", "archived_on"])
		)

	def test_purge_removes_whole_families_only_after_retention(self):
		root, video = self.family()
		fresh = project("Fresh trash")
		for name, days in ((root.name, -31), (fresh.name, -29)):
			frappe.db.set_value(
				"Media Project",
				name,
				{"status": "Archived", "archived_on": add_days(now_datetime(), days)},
			)
		with patch("frappe.db.commit"):
			trash.purge_expired_trash()
		self.assertFalse(frappe.db.exists("Media Project", root.name))
		self.assertFalse(frappe.db.exists("Media Project", video.name))
		self.assertTrue(frappe.db.exists("Media Project", fresh.name))
