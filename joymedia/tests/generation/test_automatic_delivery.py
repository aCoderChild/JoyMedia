import json
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.generation.automation import advance_automatic_run, current_delivery, delivery_context


class TestAutomaticDelivery(TestCase):
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
					json.dumps({"automatic_delivery": {"mode": "automatic"}} if enabled else {})
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
					return_value=[frappe._dict(name="shot", selected_output_asset_version=None)],
				),
				patch(
					"joymedia.services.generation.takes.scene_takes",
					return_value=[frappe._dict(name="old"), frappe._dict(name="current")],
				),
				patch("joymedia.services.generation.creative_batch._current_take", return_value="current"),
				patch("joymedia.services.generation.takes.select_scene_take") as select,
			):
				_select_automatic_outputs("project", "new-run", variant)
				self.assertEqual(expected, select.called)
				if expected:
					select.assert_called_once_with("project", "shot", 2)
					self.assertEqual("deferred", variant["automatic_selections"][0]["quality_review"])

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
