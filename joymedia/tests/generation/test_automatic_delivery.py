import json
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.generation.automation import advance_automatic_run, current_delivery, delivery_context


class TestAutomaticDelivery(TestCase):
	def test_known_critical_finding_stops_automatic_finishing(self):
		from joymedia.services.generation.creative_batch import _select_automatic_outputs

		with (
			patch(
				"frappe.get_all",
				side_effect=lambda doctype, **kwargs: []
				if doctype == "Generation Run"
				else [frappe._dict(name="shot", selected_output_asset_version="take")],
			),
			patch.object(
				frappe.db, "get_value", side_effect=["Needs Review", "Critical identity: different mascot"]
			),
		):
			with self.assertRaisesRegex(ValueError, "different mascot"):
				_select_automatic_outputs("project", "run", {"automatic_origin_run": "origin"})

	def test_completed_scene_enters_rough_cut_while_other_scenes_render(self):
		from joymedia.services.generation.creative_batch import _select_incremental_automatic_outputs

		def value(doctype, name, field, **_kwargs):
			if doctype == "Generation Run":
				return json.dumps({"automatic_delivery": {"mode": "automatic"}})
			if doctype == "Asset Version":
				return "attempt"
			if doctype == "Generation Attempt":
				return "task"
			if doctype == "Generation Task":
				return "run" if field == "generation_run" else "Completed"
			return None

		with (
			patch.object(frappe.db, "get_value", side_effect=value),
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(frappe.db, "set_value") as set_value,
			patch("frappe.get_all", return_value=[frappe._dict(name="shot")]),
			patch("joymedia.services.generation.takes.scene_takes", return_value=[frappe._dict(name="take")]),
			patch("joymedia.services.generation.creative_batch._current_take", return_value="take"),
			patch("joymedia.services.review.consistency.queue_check") as check,
			patch("joymedia.services.editing.rough_preview.queue_progressive_preview") as preview,
		):
			self.assertEqual(1, _select_incremental_automatic_outputs("project", "run", {}, "batch", 0))
		set_value.assert_called_once_with(
			"Shot", "shot", "selected_output_asset_version", "take", update_modified=False
		)
		check.assert_called_once_with("shot", "take")
		preview.assert_called_once_with("batch", 0, "project")

	def test_rough_preview_identity_changes_with_clip_frame_and_timing(self):
		from joymedia.services.editing.rough_preview import _source_signature

		shot = frappe._dict(
			name="shot",
			duration_seconds=5,
			selected_output_asset_version=None,
			keyframe_artifact="frame-a",
		)
		with (
			patch("frappe.get_all", return_value=[shot]),
			patch.object(frappe.db, "get_value", return_value=None) as first_frame,
		):
			original = _source_signature("project")
			shot.selected_output_asset_version = "clip-a"
			self.assertNotEqual(original, _source_signature("project"))
			shot.selected_output_asset_version = None
			shot.duration_seconds = 6
			self.assertNotEqual(original, _source_signature("project"))
			shot.duration_seconds = 5
			first_frame.return_value = "source-art"
			self.assertNotEqual(original, _source_signature("project"))

	def test_automatic_preview_cannot_select_a_take_from_an_older_run(self):
		from joymedia.services.generation.creative_batch import _select_automatic_outputs

		for enabled, native_run, expected in (
			(False, "new-run", False),
			(True, "old-run", False),
			(True, "new-run", True),
		):
			variant = {}

			def value(doctype, *args, **kwargs):
				return (
					(
						None
						if isinstance(args[1], (list, tuple))
						else json.dumps({"automatic_delivery": {"mode": "automatic"}} if enabled else {})
					)
					if doctype == "Generation Run"
					else "attempt"
					if doctype == "Asset Version"
					else "task"
					if doctype == "Generation Attempt"
					else native_run
				)

			with (
				self.subTest(enabled=enabled, native_run=native_run),
				patch.object(frappe.db, "get_value", side_effect=value),
				patch(
					"frappe.get_all",
					side_effect=lambda doctype, **kwargs: []
					if doctype == "Generation Run"
					else [frappe._dict(name="shot", selected_output_asset_version=None)],
				),
				patch(
					"joymedia.services.generation.takes.scene_takes",
					return_value=[frappe._dict(name="old"), frappe._dict(name="current")],
				),
				patch("joymedia.services.generation.creative_batch._current_take", return_value="current"),
				patch("joymedia.services.generation.takes.select_scene_take") as select,
				patch("joymedia.services.review.consistency.queue_check") as check,
			):
				ready = _select_automatic_outputs("project", "new-run", variant)
				self.assertEqual(expected, select.called)
				if expected:
					select.assert_called_once_with("project", "shot", 2)
					check.assert_called_once_with("shot", "take")
					self.assertFalse(ready)
					self.assertEqual("checking", variant["automatic_selections"][0]["quality_review"])

	def test_automatic_preview_follows_an_active_replacement_run(self):
		from joymedia.services.generation.creative_batch import _select_automatic_outputs

		variant = {"generation_request": {"run": "old-run"}}
		with (
			patch.object(
				frappe.db, "get_value", return_value=json.dumps({"automatic_delivery": {"mode": "automatic"}})
			),
			patch("frappe.get_all", return_value=[frappe._dict(name="replacement-run")]),
			patch("joymedia.services.generation.takes.select_scene_take") as select,
		):
			self.assertFalse(_select_automatic_outputs("project", "old-run", variant))
		self.assertEqual({"run": "replacement-run"}, variant["generation_request"])
		select.assert_not_called()

	def test_replacement_run_inherits_automatic_batch_authority(self):
		from joymedia.services.generation.creative_batch import _select_automatic_outputs

		variant = {"automatic_origin_run": "original-run"}
		with (
			patch.object(frappe.db, "get_value", return_value=None),
			patch("frappe.get_all", return_value=[]),
		):
			self.assertTrue(_select_automatic_outputs("project", "replacement-run", variant))

	def test_review_finding_is_kept_on_the_complete_preview(self):
		from joymedia.services.generation.creative_batch import _select_automatic_outputs

		variant = {"automatic_origin_run": "original-run"}
		with (
			patch.object(frappe.db, "get_value", side_effect=["Needs Review", "Prop support needs review"]),
			patch(
				"frappe.get_all",
				side_effect=lambda doctype, **kwargs: []
				if doctype == "Generation Run"
				else [frappe._dict(name="shot", selected_output_asset_version="take")],
			),
		):
			self.assertTrue(_select_automatic_outputs("project", "replacement-run", variant))
		self.assertEqual({"shot": "Prop support needs review"}, variant["preview_findings"])

	def test_a_later_usable_replacement_can_fill_a_failed_latest_run(self):
		from joymedia.services.generation.creative_batch import _select_automatic_outputs

		origin_time = datetime(2026, 1, 1)

		def value(doctype, name, fieldname, **kwargs):
			if doctype == "Asset Version":
				return "attempt"
			if doctype == "Generation Attempt":
				return "task"
			if doctype == "Generation Task":
				return "replacement-run"
			if doctype == "Generation Run":
				return frappe._dict(
					media_project="project",
					creation=origin_time
					+ (timedelta(minutes=1) if name == "replacement-run" else timedelta()),
				)
			return None

		variant = {"automatic_origin_run": "original-run"}
		with (
			patch.object(frappe.db, "get_value", side_effect=value),
			patch(
				"frappe.get_all",
				side_effect=lambda doctype, **kwargs: []
				if doctype == "Generation Run"
				else [frappe._dict(name="shot", selected_output_asset_version=None)],
			),
			patch("joymedia.services.generation.takes.scene_takes", return_value=[frappe._dict(name="take")]),
			patch("joymedia.services.generation.creative_batch._current_take", return_value="take"),
			patch("joymedia.services.generation.takes.select_scene_take") as select,
			patch("joymedia.services.review.consistency.queue_check"),
		):
			self.assertFalse(_select_automatic_outputs("project", "failed-latest-run", variant))
		select.assert_called_once_with("project", "shot", 1)

	def test_context_restores_the_previous_mode_even_on_failure(self):
		self.assertIsNone(current_delivery())
		with delivery_context({"delivery_mode": "automatic"}, "batch"):
			with self.assertRaises(ValueError), delivery_context({"delivery_mode": "assisted"}):
				self.assertIsNone(current_delivery())
				raise ValueError("failed submission")
			self.assertEqual("batch", current_delivery()["batch"])
		self.assertIsNone(current_delivery())

	def test_dispatch_is_scoped_to_active_explicitly_automatic_runs(self):
		for status, policy, expected in (
			("Running", {}, False),
			("Cancelled", {"automatic_delivery": {"mode": "automatic"}}, False),
			("Queued", {"automatic_delivery": {"mode": "automatic"}}, True),
		):
			with (
				self.subTest(status=status, policy=policy),
				patch.object(
					frappe.db,
					"get_value",
					return_value=frappe._dict(status=status, project_snapshot_json=json.dumps(policy)),
				),
				patch("joymedia.services.generation.orchestrator.refresh_run") as refresh,
				patch("joymedia.services.generation.orchestrator.submit_run") as submit,
			):
				advance_automatic_run("run")
				self.assertEqual(expected, refresh.called)
				self.assertEqual(expected, submit.called)
