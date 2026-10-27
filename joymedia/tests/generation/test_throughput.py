from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation.creative_batch import _nonretryable_scene_failure
from joymedia.services.generation.throughput import _summarize
from joymedia.services.generation.timing import record_comfy_execution


class TestThroughputReport(FrappeTestCase):
	def test_gpu_time_uses_provider_events(self):
		attempt = frappe._dict(timing_json=None)
		record_comfy_execution(
			attempt,
			{
				"status": {
					"messages": [
						["execution_start", {"timestamp": 1000}],
						["execution_error", {"timestamp": 3100}],
					]
				}
			},
		)
		self.assertEqual(2.1, frappe.parse_json(attempt.timing_json)["comfy_execution_seconds"])

	@patch("joymedia.services.generation.creative_batch.frappe.get_all")
	def test_automatic_redraw_requires_revision_after_latest_input_failure(self, get_all):
		get_all.side_effect = [
			[frappe._dict(name="TASK-1", shot="SHOT-1")],
			[frappe._dict(status="Failed", failure_class="Input", error_summary="Ambiguous product")],
		]
		self.assertEqual("SHOT-1", _nonretryable_scene_failure("RUN-1", ["SHOT-1"])["shot"])
		get_all.side_effect = [
			[frappe._dict(name="TASK-1", shot="SHOT-1")],
			[frappe._dict(status="Completed", failure_class=None, error_summary=None)],
		]
		self.assertIsNone(_nonretryable_scene_failure("RUN-1", ["SHOT-1"]))

	def test_failed_runtime_and_stage_times_are_counted(self):
		start = datetime(2026, 10, 23, 10, 0, 0)
		rows = [
			frappe._dict(
				status="Completed",
				output_media_type="Video",
				failure_class=None,
				queued_at=start,
				started_at=start + timedelta(seconds=2),
				runtime_seconds=80,
				timing_json='{"input_staging_seconds":10}',
			),
			frappe._dict(
				status="Failed",
				output_media_type="Image",
				failure_class="Input",
				queued_at=start,
				started_at=start + timedelta(seconds=4),
				runtime_seconds=100,
				timing_json='{"input_staging_seconds":20,"comfy_execution_seconds":90}',
			),
		]
		summary = _summarize(rows)
		self.assertEqual(0.5, summary["acceptance_rate"])
		self.assertEqual(1, summary["accepted_video_clips"])
		self.assertEqual(0.042, summary["accepted_clips_per_hour"])
		self.assertEqual(90, summary["known_failed_comfy_seconds"])
		self.assertEqual(15, summary["stage_mean_seconds"]["input_staging_seconds"])
		self.assertEqual(3, summary["observed_queue_wait_p50_seconds"])
		self.assertEqual(10, summary["observed_non_comfy_p50_seconds"])
		self.assertEqual(10, summary["observed_non_comfy_max_seconds"])
