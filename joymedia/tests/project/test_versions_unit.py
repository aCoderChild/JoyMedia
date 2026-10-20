from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.project import versions


def row(name, **values):
	return frappe._dict(
		name=name,
		owner="owner@example.com",
		project_name=name,
		product_name="Same product",
		video_idea="A film",
		status="Draft",
		modified="2026-10-16",
		version_of=values.get("version_of"),
		version_label=values.get("version_label"),
		version_kind="Creative",
		current_edit=values.get("current_edit"),
		current_output_asset_version=values.get("current_output_asset_version"),
		**{
			k: v
			for k, v in values.items()
			if k not in ("version_of", "version_label", "current_edit", "current_output_asset_version")
		},
	)


class TestVersionCards(TestCase):
	def cards(self, rows, **args):
		with patch("frappe.get_list", return_value=rows), patch("frappe.get_roles", return_value=[]):
			return versions.card_rows(**args)

	def test_same_product_is_not_automatically_merged(self):
		self.assertEqual(self.cards([row("A"), row("B")])["total"], 2)

	def test_explicit_family_has_one_card_and_opens_working_edit(self):
		rows = [row("A", current_edit="B"), row("B", version_of="A", current_output_asset_version="EXPORT")]
		card = self.cards(rows)["items"][0]
		self.assertEqual((card["name"], card["open_project"], card["edit_count"]), ("A", "B", 2))
		self.assertTrue(card["has_video"])

	def test_searching_an_edit_finds_its_parent(self):
		result = self.cards(
			[row("A"), row("B", version_of="A", version_label="Warm light")], search="warm light"
		)
		self.assertEqual([r["name"] for r in result["items"]], ["A"])

	def test_paging_and_counts_use_roots(self):
		result = self.cards([row("A"), row("B", version_of="A"), row("C")], page_length=1)
		self.assertEqual(result["total"], 2)
		self.assertEqual(len(result["items"]), 1)
		self.assertEqual(result["counts_by_status"]["Draft"], 2)

	def test_archiving_root_hides_family_but_archive_filter_finds_it(self):
		root = row("A")
		root.status = "Archived"
		rows = [root, row("B", version_of="A")]
		self.assertEqual(self.cards(rows)["total"], 0)
		self.assertEqual(self.cards(rows, status="Archived")["total"], 1)

	def test_foreign_owner_cannot_become_visible_working_edit(self):
		root, child = row("A", current_edit="B"), row("B", version_of="A")
		child.owner = "stranger@example.com"
		self.assertEqual(self.cards([root, child])["items"][0]["open_project"], "A")

	def test_invalid_paging_fails(self):
		with self.assertRaises(frappe.ValidationError):
			self.cards([], start="invalid")

	def test_export_manifest_freezes_clip_values(self):
		import json

		project = row("A")
		clips = [{"source_asset_version": "V1", "source_in_frame": 5, "source_out_frame": 30}]
		with patch("frappe.get_all", return_value=[]):
			manifest = versions.export_manifest(project, clips, "signature")
		clips[0]["source_in_frame"] = 9
		self.assertEqual(json.loads(manifest)["clips"][0]["source_in_frame"], 5)


class TestExportFreshness(TestCase):
	def test_legacy_export_has_no_invented_freshness(self):
		self.assertIsNone(versions.exported_edit_is_outdated(row("project"), None))

	def test_fresh_export_does_not_inherit_an_old_generation_runs_outdated_flag(self):
		project = row("project")
		manifest = {
			"timeline_signature": "same",
			"project_state": {"product_name": "Same product"},
			"selected_takes": [],
		}
		with patch("joymedia.services.editing.post_production.timeline_signature", return_value="same"):
			self.assertFalse(versions.exported_edit_is_outdated(project, manifest))
			project.product_name = "New product"
			self.assertTrue(versions.exported_edit_is_outdated(project, manifest))

	def test_changing_the_direction_invalidates_the_export_even_when_the_take_is_unchanged(self):
		manifest = {
			"timeline_signature": "same",
			"project_state": {},
			"selected_takes": [
				{
					"name": "s",
					"selected_output_asset_version": "take",
					"image_prompt": "old",
					"generation_prompt": "old",
					"motion_plan_json": None,
				}
			],
		}
		with (
			patch("joymedia.services.editing.post_production.timeline_signature", return_value="same"),
			patch.object(
				frappe.db,
				"get_value",
				return_value=frappe._dict(
					selected_output_asset_version="take",
					image_prompt="new",
					generation_prompt="old",
					motion_plan_json=None,
				),
			),
		):
			self.assertTrue(versions.exported_edit_is_outdated(row("project"), manifest))
