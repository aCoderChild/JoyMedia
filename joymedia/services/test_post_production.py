from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import post_production


class TestSegmentedSoundtrack(FrappeTestCase):
	def test_long_soundtrack_is_split_into_short_equal_segments(self):
		for seconds in (4, 21, 31, 61):
			durations = post_production.segment_durations(seconds)
			frames = [int(duration * 24) for duration in durations]

			# H3 snaps segments down to 17k+5 frames, so each must already sit on that grid.
			self.assertTrue(all(frame % 17 == 5 for frame in frames), (seconds, frames))
			self.assertGreaterEqual(sum(frames), seconds * 24)
			self.assertTrue(all(3 <= duration <= post_production.SEGMENT_SECONDS + 0.2 for duration in durations))

	def test_segmented_prompt_marks_each_cut_for_h3(self):
		prompt = post_production.segmented_prompt(["Open.", "Go on.", "End."], [4.5, 4.5, 4.5])

		self.assertEqual(
			"[Shot 1] Open.\n---\n[Shot 2] At 00:04.500, Go on.\n---\n[Shot 3] At 00:09.000, End.", prompt
		)

	@patch("joymedia.services.comfyui_client.upload_local_file", return_value={"server_path": "first.png"})
	def test_soundtrack_workflow_starts_from_a_frame_without_dangling_nodes(self, upload):
		workflow = post_production._soundtrack_workflow("first.png", "soft piano", 31)

		context = workflow["328"]["inputs"]
		self.assertEqual(["joymedia_first_frame", 0], context["first_frame"])
		self.assertNotIn("seed_video", context)
		self.assertEqual(7, len(context["segment_seconds"].split(",")))
		self.assertEqual(7, context["prompt"].count("[Shot "))
		links = [
			value[0] for node in workflow.values() for value in node["inputs"].values()
			if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
		]
		self.assertTrue(all(link in workflow for link in links))
		self.assertEqual(["330", 0], workflow[post_production.SOUNDTRACK_SAVE_NODE]["inputs"]["video"])


class TestPostProductionStatus(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.project = frappe.get_doc({
			"doctype": "Media Project",
			"project_name": "Test Finishing Project",
			"product_name": "Test Product",
			"total_duration_seconds": 10,
			"delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	@patch("joymedia.services.post_production.frappe.db.commit")
	@patch("joymedia.services.post_production.is_render_alive", return_value=False)
	def test_finishing_whose_job_died_is_reported_failed(self, alive, commit):
		self.project.db_set("post_production_status", "Running")

		status = post_production.get_post_production_status(self.project.name)

		self.assertEqual("Failed", status["status"])
		self.assertTrue(status["error"])

	@patch("joymedia.services.post_production.frappe.db.commit")
	@patch("joymedia.services.post_production.is_render_alive", return_value=True)
	def test_running_finishing_is_not_queued_twice(self, alive, commit):
		self.project.db_set("post_production_status", "Running")

		with patch("joymedia.services.post_production.enqueue_render") as enqueue:
			self.assertEqual({"status": "Running"}, post_production.queue_post_production_internal(self.project.name))
		enqueue.assert_not_called()
