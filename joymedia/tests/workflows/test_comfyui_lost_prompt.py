from unittest import TestCase
from unittest.mock import patch

import requests

from joymedia.services.generation.creative_batch import _defer_lost_comfy_job
from joymedia.services.workflows.comfyui import ComfyJobLostError, run_workflow_to_bytes


class TestLostPrompt(TestCase):
	def test_lost_job_is_retried_twice_without_replacing_saved_script(self):
		variant = {"status": "Planning", "script": {"title": "saved"}, "project": "existing"}
		with patch("joymedia.services.generation.creative_batch.time.time", return_value=100):
			self.assertTrue(_defer_lost_comfy_job(variant, ComfyJobLostError("lost")))
			self.assertEqual(130, variant["retry_after"])
			self.assertTrue(_defer_lost_comfy_job(variant, ComfyJobLostError("lost")))
			self.assertFalse(_defer_lost_comfy_job(variant, ComfyJobLostError("lost")))
		self.assertEqual({"title": "saved"}, variant["script"])
		self.assertEqual("existing", variant["project"])

	@patch("joymedia.services.workflows.comfyui.MISSING_PROMPT_POLLS", 2)
	@patch("joymedia.services.workflows.comfyui.time.sleep")
	@patch(
		"joymedia.services.workflows.comfyui.get_queue",
		return_value={"queue_running": [], "queue_pending": []},
	)
	@patch("joymedia.services.workflows.comfyui.get_history", return_value={})
	@patch("joymedia.services.workflows.comfyui.submit_workflow", return_value={"prompt_id": "lost"})
	def test_missing_prompt_stops_without_interrupting_other_work(self, submit, history, queue, sleep):
		with patch("joymedia.services.workflows.comfyui.interrupt") as interrupt:
			with self.assertRaises(ComfyJobLostError):
				run_workflow_to_bytes({}, "save", base_url="http://test")
			interrupt.assert_not_called()

	@patch("joymedia.services.workflows.comfyui.MISSING_PROMPT_POLLS", 2)
	@patch("joymedia.services.workflows.comfyui.time.sleep")
	@patch("joymedia.services.workflows.comfyui.download_output", return_value=b"ok")
	@patch("joymedia.services.workflows.comfyui.get_queue")
	@patch("joymedia.services.workflows.comfyui.get_history")
	@patch("joymedia.services.workflows.comfyui.submit_workflow", return_value={"prompt_id": "p"})
	def test_queued_prompt_and_transient_queue_error_are_not_lost(
		self, submit, history, queue, download, sleep
	):
		history.side_effect = [
			{},
			{},
			{},
			{"p": {"status": {"completed": True}, "outputs": {"save": {"images": [{"filename": "x"}]}}}},
		]
		queue.side_effect = [
			requests.ConnectionError("down"),
			{"queue_running": [], "queue_pending": [[1, "p"]]},
			{"queue_running": [], "queue_pending": []},
		]
		self.assertEqual(b"ok", run_workflow_to_bytes({}, "save", base_url="http://test"))
