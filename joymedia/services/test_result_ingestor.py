from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from . import result_ingestor


class IntegrationTestResultIngestor(IntegrationTestCase):
	def test_find_primary_mp4_accepts_comfyui_save_video_image_output(self):
		output = {"filename": "TASK-00001_ATT-00018_00001_.mp4", "type": "output"}
		history = {"outputs": {"92": {"images": [output], "animated": [True]}}}

		self.assertEqual(output, result_ingestor._find_primary_mp4(history))

	def test_find_continuation_state_accepts_sato_text_output_and_returns_basename(self):
		history = {
			"outputs": {
				"272": {
					"text": ["h3_latents/TASK-00001_ATT-00001_state_00001.h3latent.safetensors"]
				}
			}
		}

		self.assertEqual(
			"TASK-00001_ATT-00001_state_00001.h3latent.safetensors",
			result_ingestor._find_continuation_state(history),
		)

	@patch("joymedia.services.result_ingestor.download_output", return_value=b"video-bytes")
	@patch("joymedia.services.result_ingestor.frappe.get_doc")
	def test_completed_artifact_is_copied_to_a_private_frappe_file(self, get_doc, download_output):
		artifact = frappe._dict(
			name="GART-00001",
			frappe_file=None,
			remote_filename="JOB-00001_ATT-00001.mp4",
			remote_subfolder="",
			remote_file_type="output",
		)
		artifact.save = MagicMock()
		attempt = frappe._dict(comfyui_endpoint_url="http://worker:8188")
		file_doc = frappe._dict(file_url="/private/files/JOB-00001_ATT-00001.mp4")
		file_doc.insert = MagicMock()
		get_doc.return_value = file_doc

		result_ingestor._store_artifact_file_in_frappe(
			artifact,
			attempt,
			{"filename": "JOB-00001_ATT-00001.mp4", "subfolder": "", "type": "output"},
		)

		download_output.assert_called_once_with(
			"JOB-00001_ATT-00001.mp4", "", "output", base_url="http://worker:8188"
		)
		self.assertEqual(artifact.frappe_file, "/private/files/JOB-00001_ATT-00001.mp4")
		file_doc.insert.assert_called_once_with(ignore_permissions=True)
		artifact.save.assert_called_once_with(ignore_permissions=True)

	def test_sync_active_attempts_polls_external_attempts(self):
		with (
			patch.object(
				result_ingestor.frappe,
				"get_all",
				return_value=[
					frappe._dict(name="ATT-EXTERNAL", external_job_id="comfy-1"),
					frappe._dict(name="ATT-NO-ID", external_job_id=None),
				],
			) as get_all,
			patch.object(
				result_ingestor,
				"sync_attempt_result",
				return_value={"status": "Completed", "output_artifact": "GART-00001"},
			) as sync_attempt_result,
			patch.object(result_ingestor.frappe.db, "commit") as commit,
		):
			result = result_ingestor.sync_active_attempts()

		get_all.assert_called_once_with(
			"Generation Attempt",
			filters={"status": ["in", ["Queued", "Running"]]},
			fields=["name", "external_job_id"],
		)
		sync_attempt_result.assert_called_once_with("ATT-EXTERNAL")
		commit.assert_called_once()
		self.assertEqual(
			result,
			[
				{
					"attempt": "ATT-EXTERNAL",
					"status": "Completed",
					"output_artifact": "GART-00001",
				}
			],
		)

	def _sync_with(self, attempt, history, queue_state=None):
		get_doc = frappe.get_doc

		def get_attempt(doctype, *args, **kwargs):
			if doctype == "Generation Attempt":
				return attempt
			return get_doc(doctype, *args, **kwargs)

		with (
			patch.object(result_ingestor.frappe, "get_doc", side_effect=get_attempt),
			patch.object(result_ingestor, "get_attempt_artifact", return_value=None),
			patch.object(result_ingestor, "get_history", return_value=history),
			patch.object(result_ingestor, "get_queue_state", return_value=queue_state) as get_queue_state,
			patch.object(result_ingestor, "probe_output", return_value=False),
			patch.object(result_ingestor, "_refresh_parent_execution_state") as refresh_parent,
		):
			result = result_ingestor._sync_attempt_result(attempt.name)
		return result, get_queue_state, refresh_parent

	def _attempt(self, **values):
		attempt = frappe._dict(
			name="ATT-SYNC",
			status="Queued",
			external_job_id="comfy-1",
			comfyui_endpoint_url="http://worker:8188",
			queued_at="2020-01-01 00:00:00",
			started_at=None,
			**values,
		)
		attempt.save = MagicMock()
		return attempt

	def test_missing_history_uses_running_queue_state(self):
		attempt = self._attempt()

		result, get_queue_state, refresh_parent = self._sync_with(attempt, {}, "running")

		get_queue_state.assert_called_once_with("comfy-1", base_url="http://worker:8188")
		self.assertEqual({"status": "Running"}, result)
		self.assertTrue(attempt.started_at)
		attempt.save.assert_called_once_with(ignore_permissions=True)
		refresh_parent.assert_called_once_with("ATT-SYNC")

	def test_missing_history_keeps_pending_prompt_queued(self):
		attempt = self._attempt()

		result, _, _ = self._sync_with(attempt, {}, "pending")

		self.assertEqual({"status": "Queued"}, result)

	def test_job_missing_from_history_and_queue_fails_attempt(self):
		attempt = self._attempt()

		result, _, refresh_parent = self._sync_with(attempt, {}, None)

		self.assertEqual({"status": "Failed"}, result)
		self.assertEqual("Failed", attempt.status)
		self.assertEqual("Infrastructure", attempt.failure_class)
		self.assertIn("dropped this job", attempt.error_summary)
		self.assertIn("no longer present", attempt.error_details)
		attempt.save.assert_called_once_with(ignore_permissions=True)
		refresh_parent.assert_called_once_with("ATT-SYNC")

	def test_job_missing_just_after_submission_stays_queued(self):
		attempt = self._attempt()
		attempt.queued_at = frappe.utils.now()

		result, _, _ = self._sync_with(attempt, {}, None)

		self.assertEqual({"status": "Queued"}, result)

	def test_completed_history_without_mp4_fails_attempt_instead_of_raising(self):
		attempt = self._attempt()
		history = {"comfy-1": {"status": {"completed": True}, "outputs": {"9": {"images": []}}}}

		result, get_queue_state, refresh_parent = self._sync_with(attempt, history)

		get_queue_state.assert_not_called()
		self.assertEqual({"status": "Failed"}, result)
		self.assertEqual("Generation", attempt.failure_class)
		self.assertIn("could not be rendered", attempt.error_summary)
		self.assertIn("no usable MP4", attempt.error_details)
		refresh_parent.assert_called_once_with("ATT-SYNC")

	def test_unprocessable_completed_output_fails_attempt(self):
		attempt = self._attempt()
		output = {"filename": "clip.mp4", "type": "output"}
		history = {"comfy-1": {"status": {"completed": True}, "outputs": {"9": {"videos": [output]}}}}

		with patch.object(
			result_ingestor,
			"_ingest_completed_output",
			side_effect=result_ingestor.UnusableComfyUIOutput("bad video"),
		):
			result, _, _ = self._sync_with(attempt, history)

		self.assertEqual({"status": "Failed"}, result)
		self.assertEqual("bad video", attempt.error_details)
