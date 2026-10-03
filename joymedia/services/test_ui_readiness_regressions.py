from contextlib import nullcontext
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.joymedia.doctype.generation_attempt.generation_attempt import (
	_invalidate_manual_regeneration_outputs,
)
from joymedia.services.generation_runner import submit_attempt


class TestUIReadinessRegressions(FrappeTestCase):
	def test_chained_reroll_attempt_waits_for_new_upstream_output(self):
		attempt = frappe._dict(
			name="ATT-DOWNSTREAM",
			status="Pending",
			generation_task="JOB-DOWNSTREAM",
		)
		job = frappe._dict(
			name="JOB-DOWNSTREAM",
			depends_on_task="JOB-UPSTREAM",
		)

		with (
			patch(
				"joymedia.services.generation_runner.filelock",
				return_value=nullcontext(),
			),
			patch(
				"joymedia.services.generation_runner.frappe.get_doc",
				side_effect=[attempt, job],
			),
			patch(
				"joymedia.services.generation_runner.attach_chained_first_frame",
				return_value=False,
			),
			patch("joymedia.services.generation_runner.submit_workflow") as submit_workflow,
		):
			result = submit_attempt(attempt.name)

		self.assertEqual(
			result,
			{"deferred": True, "dependency": "JOB-UPSTREAM"},
		)
		submit_workflow.assert_not_called()
		self.assertEqual(attempt.status, "Pending")

	def test_manual_regeneration_invalidates_explicit_project_export(self):
		job = frappe._dict(name="JOB-00001", generation_run="RUN-00001")
		run = frappe._dict(name="RUN-00001", media_project="PROJECT-00001")

		with (
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.get_doc",
				return_value=run,
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.db.set_value"
			) as set_value,
			patch(
				"joymedia.services.timeline_editor._invalidate_project_output"
			) as invalidate_project_output,
		):
			_invalidate_manual_regeneration_outputs(job)

		set_value.assert_called_once_with(
			"Generation Run",
			"RUN-00001",
			{
				"completed_at": None,
				"failure_class": None,
				"error_summary": None,
			},
			update_modified=False,
		)
		invalidate_project_output.assert_called_once_with("PROJECT-00001")