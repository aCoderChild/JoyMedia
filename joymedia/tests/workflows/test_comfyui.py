import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflows.comfyui import (
	download_output,
	get_history,
	get_object_info,
	get_queue_state,
	get_request_auth,
	get_system_stats,
	interrupt,
	run_workflow_to_bytes,
	submit_workflow,
)


class TestComfyUIClient(FrappeTestCase):
	@patch(
		"joymedia.services.workflows.comfyui.frappe.conf",
		{"comfyui_username": "comfy-user", "comfyui_password": "comfy-pass"},
	)
	def test_request_auth_uses_configured_basic_auth(self):
		self.assertEqual(("comfy-user", "comfy-pass"), get_request_auth())

	@patch("joymedia.services.workflows.comfyui.requests.post")
	def test_upload_rejects_corrupt_image_before_queueing_it(self, post):
		from joymedia.services.workflows.comfyui import upload_local_file

		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "broken.png"
			path.write_bytes(b"not an image")
			with self.assertRaises(frappe.ValidationError):
				upload_local_file(path, base_url="http://comfyui")

		post.assert_not_called()

	@patch("joymedia.services.workflows.comfyui.filelock", return_value=nullcontext())
	@patch("joymedia.services.workflows.comfyui.requests.post")
	def test_upload_serializes_requests_before_calling_comfyui(self, post, lock):
		from joymedia.services.workflows.comfyui import upload_local_file

		response = Mock(ok=True)
		response.json.return_value = {"name": "input.png"}
		post.return_value = response
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "valid.png"
			from PIL import Image

			Image.new("RGB", (1, 1), "white").save(path)
			upload_local_file(path, base_url="http://comfyui")

		lock.assert_called_once_with("joymedia-comfyui-upload")
		post.assert_called_once()

	@patch(
		"joymedia.services.workflows.comfyui.frappe.conf",
		{"comfyui_username": "comfy-user", "comfyui_password": "comfy-pass"},
	)
	@patch("joymedia.services.workflows.comfyui.requests.post")
	def test_submit_workflow_sends_basic_auth(self, post):
		response = Mock(ok=True)
		response.json.return_value = {"prompt_id": "prompt-1"}
		post.return_value = response

		submit_workflow({"node": {"class_type": "Example"}}, base_url="http://comfyui")

		self.assertEqual(("comfy-user", "comfy-pass"), post.call_args.kwargs["auth"])

	@patch(
		"joymedia.services.workflows.comfyui.frappe.conf",
		{"comfyui_username": "comfy-user", "comfyui_password": "comfy-pass"},
	)
	@patch("joymedia.services.workflows.comfyui.requests.get")
	def test_read_requests_send_basic_auth(self, get):
		response = Mock(ok=True, content=b"video")
		response.json.return_value = {"prompt-1": {}}
		get.return_value = response

		get_history("prompt-1", base_url="http://comfyui")
		get_system_stats(base_url="http://comfyui")
		get_object_info(base_url="http://comfyui")
		download_output("video.mp4", base_url="http://comfyui")

		self.assertEqual(4, get.call_count)
		for call in get.call_args_list:
			self.assertEqual(("comfy-user", "comfy-pass"), call.kwargs["auth"])

	@patch("joymedia.services.workflows.comfyui.frappe.conf", {})
	@patch("joymedia.services.workflows.comfyui.requests.get")
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

	@patch("joymedia.services.workflows.comfyui.frappe.conf", {})
	@patch("joymedia.services.workflows.comfyui.requests.post")
	def test_interrupt_targets_prompt(self, post):
		response = Mock(ok=True)
		post.return_value = response

		interrupt(prompt_id="prompt-running", base_url="http://comfyui")

		self.assertEqual("http://comfyui/interrupt", post.call_args.args[0])
		self.assertEqual({"prompt_id": "prompt-running"}, post.call_args.kwargs["json"])

	@patch("joymedia.services.workflows.comfyui.time.sleep")
	@patch("joymedia.services.workflows.comfyui.download_output", return_value=b"video")
	@patch("joymedia.services.workflows.comfyui.get_history")
	@patch("joymedia.services.workflows.comfyui.submit_workflow", return_value={"prompt_id": "p1"})
	def test_run_workflow_survives_brief_connection_drops(self, submit, get_history, download, sleep):
		done = {
			"p1": {"status": {"completed": True}, "outputs": {"save": {"videos": [{"filename": "out.mp4"}]}}}
		}
		get_history.side_effect = [
			requests.ConnectionError("tunnel down"),
			requests.ReadTimeout("slow"),
			done,
		]

		self.assertEqual(b"video", run_workflow_to_bytes({}, "save", base_url="http://comfyui"))
		self.assertEqual(3, get_history.call_count)

	@patch("joymedia.services.workflows.comfyui.MAX_POLL_FAILURES", 2)
	@patch("joymedia.services.workflows.comfyui.time.sleep")
	@patch("joymedia.services.workflows.comfyui.get_history", side_effect=requests.ConnectionError("down"))
	@patch("joymedia.services.workflows.comfyui.submit_workflow", return_value={"prompt_id": "p1"})
	def test_run_workflow_gives_up_when_comfyui_stays_unreachable(self, submit, get_history, sleep):
		with self.assertRaises(requests.ConnectionError):
			run_workflow_to_bytes({}, "save", base_url="http://comfyui")
		self.assertEqual(3, get_history.call_count)


class TestComfyUIControlRoutes(FrappeTestCase):
	@patch(
		"joymedia.services.workflows.comfyui.frappe.conf",
		{
			"comfyui_control_routes": {"http://data:8188": "http://control:18189"},
		},
	)
	@patch("joymedia.services.workflows.comfyui.requests.post")
	@patch("joymedia.services.workflows.comfyui.requests.get")
	def test_explicit_control_route_moves_json_calls_to_the_same_servers_control_transport(self, get, post):
		get.return_value = Mock(ok=True)
		get.return_value.json.return_value = {}
		post.return_value = Mock(ok=True)
		post.return_value.json.return_value = {"prompt_id": "prompt-a"}
		get_history("prompt-a", base_url="http://data:8188")
		get_queue_state("prompt-a", base_url="http://data:8188")
		submit_workflow({}, base_url="http://data:8188")
		self.assertEqual(
			["http://control:18189/history/prompt-a", "http://control:18189/queue"],
			[c.args[0] for c in get.call_args_list],
		)
		self.assertEqual("http://control:18189/prompt", post.call_args.args[0])

	@patch(
		"joymedia.services.workflows.comfyui.frappe.conf",
		{
			"comfyui_base_url": "http://default:8188",
			"comfyui_control_routes": {"http://default:8188": "http://control:18189"},
		},
	)
	def test_an_alternate_historical_server_is_never_redirected_to_the_default_server(self):
		from joymedia.services.workflows.comfyui import get_control_url

		self.assertEqual("http://other:8188", get_control_url("http://other:8188/"))
		self.assertEqual("http://control:18189", get_control_url())

	@patch(
		"joymedia.services.workflows.comfyui.frappe.conf",
		{"comfyui_control_routes": {"http://data": "file:///tmp"}},
	)
	def test_invalid_control_routes_fail_before_any_network_request(self):
		from joymedia.services.workflows.comfyui import get_control_url

		with self.assertRaises(ValueError):
			get_control_url("http://data")


class TestWorkflowEndpointRouting(TestCase):
	def test_operator_route_is_per_workflow_and_does_not_redirect_other_versions(self):
		from joymedia.services.workflows.comfyui import endpoint_for_workflow

		with patch.dict(
			frappe.conf,
			{
				"joymedia_workflow_endpoints": {"WF-ISOLATED": "http://isolated:8190/"},
				"comfyui_base_url": "http://primary:8188",
			},
		):
			self.assertEqual(endpoint_for_workflow("WF-ISOLATED"), "http://isolated:8190")
			self.assertEqual(endpoint_for_workflow("WF-OTHER"), "http://primary:8188")

	def test_bad_endpoint_configuration_fails_before_submission(self):
		from joymedia.services.workflows.comfyui import endpoint_for_workflow

		for value in [
			False,
			"/local/path",
			"file:///tmp/model",
			"http://user:password@server:8188",
			"http://server:8188?token=secret",
		]:
			with (
				patch.dict(frappe.conf, {"joymedia_workflow_endpoints": {"WF": value}}),
				self.assertRaises(ValueError),
			):
				endpoint_for_workflow("WF")
