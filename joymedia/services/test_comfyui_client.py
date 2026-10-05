from unittest.mock import Mock, patch

import requests

from frappe.tests.utils import FrappeTestCase

from joymedia.services.comfyui_client import (
	download_output,
	get_history,
	get_queue_state,
	get_request_auth,
	get_system_stats,
	interrupt,
	run_workflow_to_bytes,
	submit_workflow,
)


class TestComfyUIClient(FrappeTestCase):
	@patch(
		"joymedia.services.comfyui_client.frappe.conf",
		{"comfyui_username": "comfy-user", "comfyui_password": "comfy-pass"},
	)
	def test_request_auth_uses_configured_basic_auth(self):
		self.assertEqual(("comfy-user", "comfy-pass"), get_request_auth())

	@patch(
		"joymedia.services.comfyui_client.frappe.conf",
		{"comfyui_username": "comfy-user", "comfyui_password": "comfy-pass"},
	)
	@patch("joymedia.services.comfyui_client.requests.post")
	def test_submit_workflow_sends_basic_auth(self, post):
		response = Mock(ok=True)
		response.json.return_value = {"prompt_id": "prompt-1"}
		post.return_value = response

		submit_workflow({"node": {"class_type": "Example"}}, base_url="http://comfyui")

		self.assertEqual(("comfy-user", "comfy-pass"), post.call_args.kwargs["auth"])

	@patch(
		"joymedia.services.comfyui_client.frappe.conf",
		{"comfyui_username": "comfy-user", "comfyui_password": "comfy-pass"},
	)
	@patch("joymedia.services.comfyui_client.requests.get")
	def test_read_requests_send_basic_auth(self, get):
		response = Mock(ok=True, content=b"video")
		response.json.return_value = {"prompt-1": {}}
		get.return_value = response

		get_history("prompt-1", base_url="http://comfyui")
		get_system_stats(base_url="http://comfyui")
		download_output("video.mp4", base_url="http://comfyui")

		self.assertEqual(3, get.call_count)
		for call in get.call_args_list:
			self.assertEqual(("comfy-user", "comfy-pass"), call.kwargs["auth"])

	@patch("joymedia.services.comfyui_client.frappe.conf", {})
	@patch("joymedia.services.comfyui_client.requests.get")
	def test_queue_state_finds_running_and_pending_prompts(self, get):
		response = Mock(ok=True)
		response.json.return_value = {
			"queue_running": [[1, "prompt-running", {}, {}, []]],
			"queue_pending": [[2, "prompt-pending", {}, {}, []]],
		}
		get.return_value = response

		self.assertEqual("running", get_queue_state("prompt-running", base_url="http://comfyui"))
		self.assertEqual("pending", get_queue_state("prompt-pending", base_url="http://comfyui"))
		self.assertIsNone(get_queue_state("prompt-gone", base_url="http://comfyui"))
		self.assertEqual("http://comfyui/queue", get.call_args.args[0])

	@patch("joymedia.services.comfyui_client.frappe.conf", {})
	@patch("joymedia.services.comfyui_client.requests.post")
	def test_interrupt_targets_prompt(self, post):
		response = Mock(ok=True)
		post.return_value = response

		interrupt(prompt_id="prompt-running", base_url="http://comfyui")

		self.assertEqual("http://comfyui/interrupt", post.call_args.args[0])
		self.assertEqual({"prompt_id": "prompt-running"}, post.call_args.kwargs["json"])

	@patch("joymedia.services.comfyui_client.time.sleep")
	@patch("joymedia.services.comfyui_client.download_output", return_value=b"video")
	@patch("joymedia.services.comfyui_client.get_history")
	@patch("joymedia.services.comfyui_client.submit_workflow", return_value={"prompt_id": "p1"})
	def test_run_workflow_survives_brief_connection_drops(self, submit, get_history, download, sleep):
		done = {"p1": {"status": {"completed": True}, "outputs": {"save": {"videos": [{"filename": "out.mp4"}]}}}}
		get_history.side_effect = [requests.ConnectionError("tunnel down"), requests.ReadTimeout("slow"), done]

		self.assertEqual(b"video", run_workflow_to_bytes({}, "save", base_url="http://comfyui"))
		self.assertEqual(3, get_history.call_count)

	@patch("joymedia.services.comfyui_client.MAX_POLL_FAILURES", 2)
	@patch("joymedia.services.comfyui_client.time.sleep")
	@patch("joymedia.services.comfyui_client.get_history", side_effect=requests.ConnectionError("down"))
	@patch("joymedia.services.comfyui_client.submit_workflow", return_value={"prompt_id": "p1"})
	def test_run_workflow_gives_up_when_comfyui_stays_unreachable(self, submit, get_history, sleep):
		with self.assertRaises(requests.ConnectionError):
			run_workflow_to_bytes({}, "save", base_url="http://comfyui")
		self.assertEqual(3, get_history.call_count)
