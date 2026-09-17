from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from joymedia.services import worker_monitor


class TestWorkerMonitor(FrappeTestCase):
	@patch("joymedia.services.worker_monitor.get_active_job_count", return_value=1)
	@patch("joymedia.services.worker_monitor.get_system_stats")
	@patch("joymedia.services.worker_monitor.frappe.get_doc")
	def test_refresh_worker_records_verified_system_telemetry(
		self, get_doc, get_system_stats, _get_active_job_count
	):
		worker = MagicMock()
		worker.name = "CUIW-00001"
		worker.status = "Active"
		worker.health_status = "Offline"
		worker.endpoint_url = "http://worker:8188"
		get_doc.return_value = worker
		get_system_stats.return_value = {
			"devices": [
				{
					"name": "NVIDIA Test GPU",
					"vram_total": 24 * worker_monitor.MIB,
					"vram_free": 12 * worker_monitor.MIB,
				}
			]
		}

		worker_monitor.refresh_worker(worker.name)

		self.assertEqual(worker.health_status, "Healthy")
		self.assertEqual(worker.gpu_name, "NVIDIA Test GPU")
		self.assertEqual(worker.vram_total_mib, 24)
		self.assertEqual(worker.vram_free_mib, 12)
		self.assertEqual(worker.active_jobs, 1)
		worker.save.assert_called_once_with(ignore_permissions=True)
