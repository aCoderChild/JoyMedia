from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.editing import post_production


class TestConcurrentTakeSwap(TestCase):
	def test_editorial_swap_retries_snapshot_conflict_without_rendering_again(self):
		clip = frappe._dict(shot="SHOT", source_asset_version="OLD")
		with (
			patch.object(post_production, "_set_status"),
			patch.object(frappe, "get_all", side_effect=[[clip], [("SHOT", "NEW")]]),
			patch.object(frappe.db, "get_value", return_value="Continuous"),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback") as rollback,
			patch("joymedia.services.editing.timeline.update_timeline_source_for_shot",
				side_effect=[frappe.QueryDeadlockError("1020"), None]) as swap,
			patch.object(post_production, "_bridge_asset_version") as render,
		):
			post_production._patch_changed_scenes("PROJECT")
		self.assertEqual(2, swap.call_count)
		rollback.assert_called_once()
		render.assert_not_called()
