from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.review.lineage import direction_changed, take_direction_changed


class TestDirectionLineage(TestCase):
	def test_json_formatting_does_not_invalidate_identical_direction(self):
		self.assertFalse(
			direction_changed({"motion_plan_json": '{"a":1,"b":2}'}, {"motion_plan_json": '{ "b":2, "a":1 }'})
		)

	def test_a_new_physical_contract_requires_new_footage(self):
		self.assertTrue(
			direction_changed({"motion_plan_json": '{"checks":["four legs"]}'}, {"motion_plan_json": "{}"})
		)

	def test_changed_start_frame_or_motion_is_not_a_completed_scene(self):
		for field in ("image_prompt", "generation_prompt"):
			self.assertTrue(direction_changed({field: "new"}, {field: "old"}))

	def test_derived_take_uses_its_original_task_not_its_new_shot_name(self):
		values = [
			frappe._dict(source_generation_attempt="attempt", derived_from=None),
			"task",
			frappe._dict(generation_run="run", shot="original"),
			' {"shots":[{"shot":"original","image_prompt":"old"}]}',
		]
		with patch.object(frappe.db, "get_value", side_effect=values):
			self.assertTrue(
				take_direction_changed(
					frappe._dict(name="copy", selected_output_asset_version="take", image_prompt="new")
				)
			)

	def test_missing_historical_lineage_does_not_invent_a_comparison(self):
		with patch.object(
			frappe.db,
			"get_value",
			return_value=frappe._dict(source_generation_attempt=None, derived_from=None),
		):
			self.assertFalse(take_direction_changed(frappe._dict(selected_output_asset_version="legacy")))


class TestAuthoredDirection(TestCase):
	def test_explicit_revision_overrides_import_without_rewriting_model_prompt(self):
		from joymedia.services.scene.direction import authored_action

		self.assertEqual(
			"One sheet with four connected plies.",
			authored_action(
				{
					"storyboard_action": "One sheet with four connected plies.",
					"generation_prompt": "Render macro",
				},
				{"action": "Four stacked sheets"},
			),
		)

	def test_imported_action_survives_simplified_provider_prompt(self):
		from joymedia.services.scene.direction import authored_action

		self.assertEqual(
			"Lift the vase.",
			authored_action({"generation_prompt": "Static vase"}, {"action": "Lift the vase."}),
		)

	def test_unscripted_direction_and_revision_invalidation(self):
		from joymedia.services.scene.direction import authored_action

		self.assertEqual("Rotate the bottle.", authored_action({"generation_prompt": "Rotate the bottle."}))
		self.assertTrue(
			direction_changed({"authored_action": "Lift the vase."}, {"authored_action": "Static vase."})
		)


class TestAuthoredActionLineage(TestCase):
	def test_release_minimal_row_resolves_authored_action_from_current_shot(self):
		row = frappe._dict(
			name="shot", selected_output_asset_version="take", generation_prompt="Render product"
		)
		values = [
			frappe._dict(source_generation_attempt="attempt", derived_from=None),
			"task",
			frappe._dict(generation_run="run", shot="shot"),
			'{"shots":[{"shot":"shot","generation_prompt":"Render product","authored_action":"Lift the vase."}]}',
		]
		current = frappe._dict(
			media_project="project",
			storyboard_beat="beat",
			source_timing="0-4",
			storyboard_action="Rotate the vase.",
		)
		with (
			patch.object(frappe.db, "get_value", side_effect=values),
			patch.object(frappe, "get_doc", side_effect=[current, frappe._dict()]),
			patch("joymedia.services.project.context._sheet_scenes", return_value={}),
		):
			self.assertTrue(take_direction_changed(row))

	def test_explicit_action_revision_cannot_reuse_legacy_take_approval(self):
		values = [
			frappe._dict(source_generation_attempt="attempt", derived_from=None),
			"task",
			frappe._dict(generation_run="run", shot="shot"),
			'{"shots":[{"shot":"shot","generation_prompt":"Static vase"}]}',
		]
		with patch.object(frappe.db, "get_value", side_effect=values):
			self.assertTrue(
				take_direction_changed(
					frappe._dict(
						name="shot",
						selected_output_asset_version="take",
						storyboard_action="Lift the vase.",
						generation_prompt="Static vase",
					)
				)
			)


class TestCopiedControlReferences(TestCase):
	def test_identical_explicit_copy_resolves_to_its_frozen_ancestor(self):
		from joymedia.services.review.lineage import _copied_reference

		rows = {
			"copy": frappe._dict(
				source="Derived", derived_from="original", file="/frame.png", content_hash="same"
			),
			"original": frappe._dict(
				source="Edited", derived_from=None, file="/frame.png", content_hash="same"
			),
		}
		with patch.object(frappe.db, "get_value", side_effect=lambda kind, name, *a, **kw: rows.get(name)):
			self.assertEqual(_copied_reference("copy", {"original"}), "original")

	def test_changed_bytes_or_unrelated_upload_do_not_reuse_old_direction(self):
		from joymedia.services.review.lineage import _copied_reference

		for source, parent, file, digest in [
			("Derived", "original", "/new.png", "new"),
			("Uploaded", None, "/frame.png", "same"),
			("Derived", "original", "/frame.png", "different"),
		]:
			rows = {
				"copy": frappe._dict(source=source, derived_from=parent, file=file, content_hash=digest),
				"original": frappe._dict(
					source="Edited", derived_from=None, file="/frame.png", content_hash="same"
				),
			}
			with patch.object(
				frappe.db, "get_value", side_effect=lambda kind, name, *a, **kw: rows.get(name)
			):
				self.assertEqual(_copied_reference("copy", {"original"}), "copy")

	def test_copy_cycle_is_not_valid_lineage(self):
		from joymedia.services.review.lineage import _copied_reference

		row = frappe._dict(source="Derived", derived_from="copy", file="/frame.png", content_hash="same")
		with patch.object(frappe.db, "get_value", return_value=row):
			self.assertEqual(_copied_reference("copy", {"original"}), "copy")
