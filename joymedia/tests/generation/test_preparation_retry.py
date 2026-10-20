from contextlib import nullcontext
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation import preparation


class TestPreparationRetry(FrappeTestCase):
	def test_deadlock_rolls_back_before_rebuilding_tasks(self):
		with (
			patch("frappe.utils.synchronization.filelock", return_value=nullcontext()),
			patch.object(frappe.db, "rollback") as rollback,
			patch.object(
				preparation,
				"_prepare_run",
				side_effect=[frappe.QueryDeadlockError("conflict"), {"status": "Queued"}],
			) as prepare,
		):
			self.assertEqual({"status": "Queued"}, preparation.prepare_run("RUN-TEST"))
			self.assertEqual(2, prepare.call_count)
			rollback.assert_called_once()

	def test_persistent_conflict_is_bounded_and_propagated(self):
		with (
			patch("frappe.utils.synchronization.filelock", return_value=nullcontext()),
			patch.object(frappe.db, "rollback") as rollback,
			patch.object(
				preparation, "_prepare_run", side_effect=frappe.QueryDeadlockError("conflict")
			) as prepare,
		):
			with self.assertRaises(frappe.QueryDeadlockError):
				preparation.prepare_run("RUN-TEST")
			self.assertEqual(3, prepare.call_count)
			self.assertEqual(3, rollback.call_count)
