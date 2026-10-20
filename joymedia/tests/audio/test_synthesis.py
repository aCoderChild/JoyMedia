import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.services.audio.synthesis import provider, synthesize


class TestSpeechProviderBoundary(TestCase):
	def test_music_workflow_is_not_treated_as_speech(self):
		workflow = frappe._dict(
			output_media_type="Audio", execution_spec={"capabilities": ["music"]}, bindings=[]
		)
		with (
			patch("joymedia.services.workflows.capabilities.configured_workflow", return_value="WF"),
			patch.object(frappe, "get_doc", return_value=workflow),
		):
			with self.assertRaisesRegex(ValueError, "speech"):
				provider()

	def test_provider_voice_is_not_validated_using_another_vendors_name_format(self):
		workflow = frappe._dict(
			output_media_type="Audio",
			execution_spec={"capabilities": ["speech"]},
			bindings=[frappe._dict(binding_key="voice")],
		)
		with (
			patch("joymedia.services.workflows.capabilities.configured_workflow", return_value="WF"),
			patch.object(frappe, "get_doc", return_value=workflow),
		):
			self.assertEqual(provider("custom-voice-id")["voice"], "custom-voice-id")

	def test_unsupported_voice_override_or_video_output_is_rejected(self):
		workflow = frappe._dict(
			output_media_type="Audio", execution_spec={"capabilities": ["speech"]}, bindings=[]
		)
		with (
			patch("joymedia.services.workflows.capabilities.configured_workflow", return_value="WF"),
			patch.object(frappe, "get_doc", return_value=workflow),
		):
			with self.assertRaisesRegex(ValueError, "voice control"):
				provider("unsupported")
			workflow.output_media_type = "Video"
			with self.assertRaisesRegex(ValueError, "produce audio"):
				provider()

	def test_generic_graph_receives_the_exact_script(self):
		workflow = frappe._dict(output_fps=24)
		adapter = Mock()
		adapter.extract_execution_metadata.return_value = {"primary_output_node_key": "save"}
		with (
			tempfile.TemporaryDirectory() as directory,
			patch.object(frappe, "get_doc", return_value=workflow),
			patch("joymedia.services.workflows.resolver.build_execution_workflow", return_value={}) as build,
			patch("joymedia.workflow_adapters.get_workflow_adapter", return_value=adapter),
			patch("joymedia.services.workflows.comfyui.run_workflow_to_bytes", return_value=b"audio"),
		):
			output = Path(directory) / "speech.wav"
			synthesize("Exact dialogue: 123.", {"workflow": "WF", "voice": "speaker"}, output, 3)
			self.assertEqual(
				build.call_args.kwargs["inputs"],
				{"generation_prompt": "Exact dialogue: 123.", "voice": "speaker"},
			)
			self.assertEqual(output.read_bytes(), b"audio")
