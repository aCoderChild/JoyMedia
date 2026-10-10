from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation_runner import _stage_generation_inputs, submit_attempt


class TestGenerationRunner(FrappeTestCase):
	@patch("joymedia.services.generation_runner.upload_frappe_file", return_value={"server_path": "previous_last.png"})
	@patch("joymedia.services.generation_runner.get_attempt_artifact")
	@patch("joymedia.services.generation_runner.get_effective_attempt")
	@patch("joymedia.services.generation_runner.frappe.get_doc")
	def test_cross_shot_last_frame_is_staged_as_the_next_first_frame(
		self, get_doc, get_effective_attempt, get_attempt_artifact, upload_frappe_file
	):
		workflow = frappe._dict(
			name="WF-I2V",
			execution_spec='{"input_preprocessing": {"compose_image_roles": ["reference_board"]}}',
			bindings=[],
		)
		artifact = frappe._dict(name="GART-LAST", artifact_role="Last Frame", frappe_file="/private/files/last.png")
		get_doc.return_value = workflow
		get_effective_attempt.return_value = frappe._dict(name="ATT-PREVIOUS", status="Completed")
		get_attempt_artifact.return_value = artifact
		job = frappe._dict(
			name="TASK-NEXT",
			workflow="WF-I2V",
			depends_on_task="TASK-PREVIOUS-VIDEO",
			dependency_artifact_role="Last Frame",
			inputs=[],
		)
		attempt = frappe._dict(name="ATT-NEXT", save=MagicMock())

		staged = _stage_generation_inputs(job, attempt)

		self.assertEqual({"first_frame": ["previous_last.png"]}, staged)
		self.assertEqual(
			{"first_frame": [{"source": "Generation Artifact", "artifact": "GART-LAST", "artifact_role": "Last Frame"}]},
			frappe.parse_json(attempt.resolved_inputs_json),
		)
		get_attempt_artifact.assert_called_once_with("ATT-PREVIOUS", "Last Frame")
		upload_frappe_file.assert_called_once_with("/private/files/last.png")

	@patch("joymedia.services.generation_runner.upload_frappe_file", return_value={"server_path": "first.png"})
	@patch("joymedia.services.generation_runner.frappe.get_doc")
	@patch("joymedia.services.generation_runner.frappe.get_all")
	def test_staged_input_roles_are_canonicalized(self, get_all, get_doc, upload_frappe_file):
		job = frappe._dict(
			name="JOB-00001",
			inputs=[frappe._dict(input_role="First Frame", asset_version="ASTV-00001")],
		)
		get_all.return_value = [
			frappe._dict(name="GENIN-00001", asset_version="ASTV-00001", input_role="First Frame")
		]
		workflow = frappe._dict(
			name="WF-I2V",
			execution_spec='{"input_preprocessing": {"compose_image_roles": ["reference_board"]}}',
			bindings=[],
		)
		asset_version = frappe._dict(name="ASTV-00001", file="/private/files/first.png")
		get_doc.side_effect = [workflow, asset_version]

		attempt = frappe._dict(name="ATT-00001", save=MagicMock())
		staged = _stage_generation_inputs(job, attempt)

		self.assertEqual({"first_frame": ["first.png"]}, staged)
		self.assertEqual(
			'{"first_frame": [{"asset_version": "ASTV-00001", "source": "Asset Version"}]}',
			attempt.resolved_inputs_json,
		)
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
		attempt = frappe._dict(name="ATT-00001", status="Pending", generation_task="JOB-00001")
		attempt.reload = MagicMock()
		attempt.save = MagicMock()
		job = MagicMock(workflow="WFV-00001", depends_on_task=None)
		get_doc.side_effect = [attempt, job]

		result = submit_attempt(attempt.name)

		self.assertEqual(result, {"prompt_id": "comfy-1"})
		stage_generation_inputs.assert_called_once_with(job, attempt)
		get_base_url.assert_called_once_with()
		submit_workflow.assert_called_once_with({}, base_url="http://legacy:8188")
		self.assertEqual(attempt.status, "Queued")
