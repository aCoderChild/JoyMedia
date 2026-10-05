import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import post_production


def _duration(path):
	return float(subprocess.run(
		["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
		capture_output=True, text=True, check=True,
	).stdout)


class TestSoundtrackLength(FrappeTestCase):
	def _soundtrack(self, rendered_seconds, film_frames):
		with tempfile.TemporaryDirectory() as temp_dir:
			video = Path(temp_dir) / "soundtrack.mp4"
			audio = Path(temp_dir) / "soundtrack.m4a"
			subprocess.run(
				["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=24:d={rendered_seconds}",
				 "-f", "lavfi", "-i", f"sine=frequency=440:duration={rendered_seconds}",
				 "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video)],
				check=True,
			)
			subprocess.run(
				["ffmpeg", "-v", "error", "-y", *post_production._soundtrack_inputs(video, film_frames),
				 "-vn", "-c:a", "aac", str(audio)],
				check=True,
			)
			return _duration(audio)

	def test_short_film_uses_the_rendered_soundtrack(self):
		self.assertAlmostEqual(21, self._soundtrack(21, 480), delta=0.1)

	def test_long_film_loops_the_capped_soundtrack_to_cover_the_picture(self):
		rendered = post_production.SOUNDTRACK_MAX_RENDER_SECONDS
		self.assertAlmostEqual(61, self._soundtrack(rendered, 60 * 24), delta=0.1)


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
