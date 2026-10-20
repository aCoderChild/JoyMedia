import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import frappe
from joymedia.api import projects


class TestStudioRefresh(unittest.TestCase):
	def test_newer_completed_run_does_not_hide_an_older_active_run(self):
		project = MagicMock(name="project")
		project.name = "PROJECT"
		with patch.object(projects.frappe, "get_doc", return_value=project), \
			patch.object(projects, "_get_latest_project_generation_run", return_value=frappe._dict(name="NEW", status="Completed")), \
			patch.object(projects.frappe, "get_all", return_value=[frappe._dict(name="OLDER", status="Running")]) as lookup, \
			patch("frappe.utils.synchronization.filelock", return_value=nullcontext()), \
			patch("joymedia.services.generation.orchestrator.refresh_run") as refresh, \
			patch.object(projects, "get_project_workspace", return_value={}):
			projects.refresh_project_studio("PROJECT")
			project._require_read_access.assert_called_once()
			refresh.assert_called_once_with("OLDER")
			self.assertEqual(1, lookup.call_args.kwargs["limit"])

	def test_foreign_project_is_rejected_before_polling(self):
		project = MagicMock()
		project._require_read_access.side_effect = frappe.PermissionError
		with patch.object(projects.frappe, "get_doc", return_value=project), patch.object(projects.frappe, "get_all") as lookup:
			with self.assertRaises(frappe.PermissionError):
				projects.refresh_project_studio("FOREIGN")
			lookup.assert_not_called()
