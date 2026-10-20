from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from joymedia.services.generation import orchestrator, run_state


class TestTerminalCancellation(TestCase):
	def test_preservation_failure_stops_delivery_without_reclassifying_provider_work(self):
		run = MagicMock(status="Running")
		run.name = "UNPROTECTED"
		with patch.object(frappe.db, "commit"), patch.object(frappe.db, "set_value") as update, patch.object(
			orchestrator, "_get_run_job_names", return_value=[]
		), patch.object(orchestrator, "_finalize_completed_shots", side_effect=ValueError("Source coverage lost")), patch.object(
			orchestrator, "_refresh_run_counters"
		) as counters, patch.object(frappe, "clear_last_message"), patch.object(
			orchestrator, "sync_media_project_status_for_run"
		), patch.object(orchestrator, "_run_summary", return_value={"status": "Failed"}):
			self.assertEqual({"status": "Failed"}, orchestrator._advance_run(run))
		counters.assert_called_once_with(run)
		self.assertEqual("Generation Run", update.call_args.args[0])
		self.assertEqual({"name": run.name, "status": ["!=", "Cancelled"]}, update.call_args.args[1])
		self.assertEqual("Finalization", update.call_args.args[2]["failure_class"])
		self.assertEqual("Source coverage lost", update.call_args.args[2]["error_summary"])

	def test_rejected_finalization_stays_failed_when_provider_tasks_completed(self):
		run = frappe._dict(name="REJECTED", status="Failed", failure_class="Finalization",
			completed_at="2026-10-18 10:00:00", error_summary="Source coverage lost")
		with patch.object(frappe, "get_all", return_value=[frappe._dict(status="Completed")]), patch.object(frappe.db, "set_value"):
			run_state._refresh_run_counters(run)
		self.assertEqual("Failed", run.status)
		self.assertEqual("Source coverage lost", run.error_summary)
		self.assertEqual(1, run.completed_tasks)
		self.assertEqual(0, run.running_tasks)

	def test_rejected_finalization_is_not_repeated_on_every_poll(self):
		run = MagicMock(status="Failed", failure_class="Finalization")
		with patch.object(frappe.db, "commit"), patch.object(orchestrator, "_finalize_completed_shots") as finalize, patch.object(orchestrator, "_run_summary", return_value={"status": "Failed"}):
			self.assertEqual({"status": "Failed"}, orchestrator._advance_run(run))
		finalize.assert_not_called()

	def test_a_stale_running_counter_update_cannot_match_a_cancelled_database_row(self):
		run = frappe._dict(name="RUN-STALE", status="Running", completed_at=None, failure_class=None, error_summary=None)
		with patch.object(frappe, "get_all", return_value=[frappe._dict(status="Cancelled")]), patch.object(frappe.db, "set_value") as update:
			run_state._refresh_run_counters(run)
		self.assertEqual({"name": run.name, "status": ["!=", "Cancelled"]}, update.call_args.args[1])

	def test_cancelled_counter_refresh_cannot_clear_the_stop_timestamp_or_report_running_work(self):
		run = frappe._dict(name="RUN-STOPPED", status="Cancelled", completed_at="2026-10-15 10:00:00")
		with patch.object(frappe, "get_all", return_value=[frappe._dict(status="Running")]), patch.object(frappe.db, "set_value") as update:
			run_state._refresh_run_counters(run)
		self.assertEqual("Cancelled", run.status)
		self.assertEqual(0, run.running_tasks)
		self.assertEqual({"name": run.name, "status": "Cancelled"}, update.call_args.args[1])
		self.assertNotIn("status", update.call_args.args[2])
		self.assertNotIn("completed_at", update.call_args.args[2])

	def test_delayed_advance_observes_the_committed_stop_before_selecting_any_take(self):
		run = MagicMock(status="Running")
		run.name = "RUN-DELAYED"
		run.reload.side_effect = lambda: setattr(run, "status", "Cancelled")
		with patch.object(frappe.db, "commit"), patch.object(orchestrator, "_finalize_completed_shots") as finalize, patch.object(
			orchestrator, "_run_summary", return_value={"status": "Cancelled"}
		):
			result = orchestrator._advance_run(run)
		self.assertEqual({"status": "Cancelled"}, result)
		finalize.assert_not_called()
