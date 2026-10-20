from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.services.runtime.transactions import persist_result


class TestComputedResultPersistence(TestCase):
	def test_short_promotion_retries_from_rollback_without_recomputing(self):
		computed = b"already-rendered-video"
		write = Mock(
			side_effect=[frappe.QueryDeadlockError("1020"), frappe.QueryDeadlockError("1020"), computed]
		)
		with patch.object(frappe.db, "commit") as commit, patch.object(frappe.db, "rollback") as rollback:
			self.assertIs(persist_result(write), computed)
			self.assertEqual(write.call_count, 3)
			self.assertEqual(rollback.call_count, 2)
			self.assertEqual(commit.call_count, 2)

	def test_conflict_budget_is_bounded(self):
		write = Mock(side_effect=frappe.QueryDeadlockError("1020"))
		with patch.object(frappe.db, "commit"), patch.object(frappe.db, "rollback") as rollback:
			with self.assertRaises(frappe.QueryDeadlockError):
				persist_result(write)
			self.assertEqual(write.call_count, 3)
			self.assertEqual(rollback.call_count, 3)

	def test_validation_and_cancel_failures_rollback_without_retry(self):
		write = Mock(side_effect=ValueError("newer take selected"))
		with patch.object(frappe.db, "commit"), patch.object(frappe.db, "rollback") as rollback:
			with self.assertRaisesRegex(ValueError, "newer take"):
				persist_result(write)
			write.assert_called_once()
			rollback.assert_called_once()
