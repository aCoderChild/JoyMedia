from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.services.generation import availability, creative_batch


class TestPartnerGpuAdmission(TestCase):
	def test_missing_service_keeps_partner_request_queued(self):
		config = frappe._dict(
			joymedia_planner={"base_url": "http://127.0.0.1:8001/v1"},
			joymedia_vision={"base_url": "http://127.0.0.1:18002/v1"},
			comfyui_base_url="http://127.0.0.1:18188",
		)
		with (
			patch.object(frappe, "conf", config),
			patch(
				"joymedia.services.workflows.comfyui.get_control_url", return_value="http://127.0.0.1:18189"
			),
			patch.object(availability.requests, "get", side_effect=requests_connection_error()),
			patch("joymedia.services.partners.is_reviewer", return_value=True),
		):
			self.assertTrue(availability.partner_batch_waits_for_gpu("partner@example.invalid"))

	def test_all_services_must_answer_json(self):
		config = frappe._dict(
			joymedia_planner={"base_url": "http://127.0.0.1:8001/v1"},
			joymedia_vision={"base_url": "http://127.0.0.1:18002/v1"},
			comfyui_base_url="http://127.0.0.1:18188",
		)
		response = Mock()
		response.json.side_effect = [{"data": []}, {"data": []}, {"system": {}}]
		with (
			patch.object(frappe, "conf", config),
			patch(
				"joymedia.services.workflows.comfyui.get_control_url", return_value="http://127.0.0.1:18189"
			),
			patch.object(availability.requests, "get", return_value=response) as get,
		):
			self.assertTrue(availability.partner_gpu_ready())
			self.assertEqual(get.call_count, 3)
			get.assert_any_call("http://127.0.0.1:18189/system_stats", timeout=(1, 2))

	def test_scheduler_does_not_submit_when_partner_gpu_is_offline(self):
		batch = frappe._dict(name="CRB-WAIT", owner="partner@example.invalid")
		with (
			patch.object(creative_batch.frappe, "get_all", return_value=[batch.name]),
			patch.object(creative_batch.frappe, "get_doc", return_value=batch),
			patch.object(creative_batch, "partner_batch_waits_for_gpu", return_value=True),
			patch.object(creative_batch, "_queue_prepare") as queue,
			patch.object(creative_batch.frappe, "enqueue") as enqueue,
		):
			creative_batch.advance_batches()
		queue.assert_not_called()
		enqueue.assert_not_called()

	def test_scheduler_resumes_same_queued_batch_when_gpu_returns(self):
		batch = frappe._dict(
			name="CRB-WAIT", owner="partner@example.invalid", variants_json='[{"status":"Queued"}]'
		)
		with (
			patch.object(creative_batch.frappe, "get_all", return_value=[batch.name]),
			patch.object(creative_batch.frappe, "get_doc", return_value=batch),
			patch.object(creative_batch, "partner_batch_waits_for_gpu", return_value=False),
			patch.object(creative_batch, "_queue_prepare") as queue,
			patch.object(creative_batch.frappe, "enqueue") as enqueue,
		):
			creative_batch.advance_batches()
		queue.assert_called_once_with(batch.name, [{"status": "Queued"}])
		enqueue.assert_not_called()


def requests_connection_error():
	from requests import ConnectionError

	return ConnectionError("GPU offline")
