from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.api.projects import cancel_project_generation
from joymedia.services.generation import orchestrator


class TestProjectCancellation(FrappeTestCase):
	def test_stop_cancels_every_active_run_of_the_authorized_project(self):
		project = MagicMock(name="project")
		project.name = "PROJECT-TEST"
		with (
			patch("joymedia.api.projects.frappe.get_doc", return_value=project),
			patch("joymedia.api.projects.frappe.get_all", return_value=["RUN-A", "RUN-B"]) as runs,
			patch.object(orchestrator, "cancel_run", side_effect=[{"name": "RUN-A", "status": "Cancelled"}, {"name": "RUN-B", "status": "Cancelled"}]) as cancel,
			patch.object(orchestrator, "sync_media_project_status_for_run"),
		):
			result = cancel_project_generation("PROJECT-TEST")
			project._require_write_access.assert_called_once()
			self.assertEqual("PROJECT-TEST", runs.call_args.kwargs["filters"]["media_project"])
			self.assertEqual(["RUN-A", "RUN-B"], [call.args[0] for call in cancel.call_args_list])
			self.assertEqual(["RUN-A", "RUN-B"], result["runs"])

	def test_stop_intent_is_committed_before_network_and_terminal_work_is_preserved(self):
		run = frappe._dict(name="RUN-A", status="Running", completed_at=None)
		events = []
		def write(doctype, filters, values, **kwargs):
			events.append(doctype)
		with (
			patch.object(orchestrator.frappe, "get_doc", return_value=run),
			patch.object(orchestrator, "_get_run_job_names", return_value=["TASK-A"]),
			patch.object(orchestrator.frappe, "get_all", return_value=[frappe._dict(external_job_id="prompt-a", status="Queued", comfyui_endpoint_url="http://comfy")]),
			patch.object(frappe.db, "commit", side_effect=lambda: events.append("commit")),
			patch.object(frappe.db, "set_value", side_effect=write) as updates,
			patch("joymedia.services.workflows.comfyui.delete_queue_prompts", side_effect=lambda *a, **k: events.append("network")),
			patch.object(orchestrator, "_refresh_run_counters") as refresh_counters,
			patch.object(orchestrator, "_run_summary", return_value={"status": "Cancelled"}),
		):
			orchestrator.cancel_run("RUN-A")
			refresh_counters.assert_called_once_with(run)
			self.assertLess(events.index("Generation Run"), events.index("network"))
			self.assertIn("commit", events[events.index("Generation Run") + 1:events.index("network")])
			for call in updates.call_args_list[1:]:
				self.assertEqual("not in", call.args[1]["status"][0])
				self.assertIn("Completed", call.args[1]["status"][1])
