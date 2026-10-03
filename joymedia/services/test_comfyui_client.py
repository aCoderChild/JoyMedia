from unittest.mock import Mock, patch

from frappe.tests.utils import FrappeTestCase

from joymedia.services.comfyui_client import (
	download_output,
	get_history,
	get_queue_state,
	get_request_auth,
	get_system_stats,
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
