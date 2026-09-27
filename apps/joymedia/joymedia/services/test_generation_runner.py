from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation_runner import _stage_generation_inputs, submit_attempt


class TestGenerationRunner(FrappeTestCase):
	@patch("joymedia.services.generation_runner.upload_frappe_file", return_value={"server_path": "first.png"})
	@patch("joymedia.services.generation_runner.frappe.get_doc")
	@patch("joymedia.services.generation_runner.frappe.get_all")
	def test_staged_input_roles_are_canonicalized(self, get_all, get_doc, upload_frappe_file):
		job = frappe._dict(name="JOB-00001")
		get_all.return_value = [
			frappe._dict(name="GENIN-00001", asset_version="ASTV-00001", input_role="First Frame")
		]
		get_doc.return_value = frappe._dict(name="ASTV-00001", file="/private/files/first.png")

		staged = _stage_generation_inputs(job)

		self.assertEqual({"first_frame": "first.png"}, staged)
		upload_frappe_file.assert_called_once_with(
			"/private/files/first.png"
		)

	@patch("joymedia.services.generation_runner.submit_workflow", return_value={"prompt_id": "comfy-1"})
	@patch("joymedia.services.generation_runner.get_base_url", return_value="http://legacy:8188")
	@patch("joymedia.services.generation_runner.resolve_attempt", return_value={})
	@patch("joymedia.services.generation_runner._stage_generation_inputs", return_value={})
	@patch("joymedia.services.generation_runner.frappe.get_doc")
	def test_configured_endpoint_is_used_for_submission(
		self,
		get_doc,
		stage_generation_inputs,
		resolve_attempt,
		get_base_url,
		submit_workflow,
	):
		attempt = frappe._dict(name="ATT-00001", status="Pending", generation_job="JOB-00001")
		attempt.reload = MagicMock()
		attempt.save = MagicMock()
		job = MagicMock(workflow_version="WFV-00001")
		get_doc.side_effect = [attempt, job]

		result = submit_attempt(attempt.name)

		self.assertEqual(result, {"prompt_id": "comfy-1"})
		stage_generation_inputs.assert_called_once_with(job)
		get_base_url.assert_called_once_with()
		submit_workflow.assert_called_once_with({}, base_url="http://legacy:8188")
		self.assertEqual(attempt.status, "Queued")
