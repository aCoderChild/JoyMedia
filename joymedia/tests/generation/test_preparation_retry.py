from contextlib import nullcontext
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation import preparation


class TestPreparationRetry(FrappeTestCase):
	def test_frozen_keyframe_repair_note_reaches_task_prompt(self):
		shot = preparation._prompt_shot(
			"SHOT-TEST",
			{
				"image_prompt": "A bear beside a table.",
				"keyframe_retry_note": "Critical geometry: bear passes through the tabletop",
				"references": [{"reference_role": "Character", "asset_version": "AV1"}],
			},
		)
		self.assertIn("keyframe_retry_note", shot)
		from joymedia.services.planning.prompts import compile_prompt_for_documents

		with patch("joymedia.services.keyframes.overlay.describe_colours", return_value="cream"):
			prompt = compile_prompt_for_documents(shot, frappe._dict(references=[]), prompt_source="image")
		self.assertIn("Retry correction:", prompt)
		self.assertIn("bear passes through the tabletop", prompt)

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
