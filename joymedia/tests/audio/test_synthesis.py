import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

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

	def test_edge_uses_the_operator_route_without_changing_dialogue_or_voice(self):
		client = Mock()
		client.save = AsyncMock()
		with (
			patch("joymedia.services.workflows.capabilities.configured_workflow", return_value=None),
			patch("frappe.conf", frappe._dict(joymedia_tts_proxy="http://127.0.0.1:12345")),
			patch("edge_tts.Communicate", return_value=client) as communicate,
			tempfile.TemporaryDirectory() as directory,
		):
			configuration = provider("vi-VN-HoaiMyNeural")
			synthesize("Exact dialogue.", configuration, Path(directory) / "voice.mp3", 3)
			communicate.assert_called_once_with(
				"Exact dialogue.",
				"vi-VN-HoaiMyNeural",
				rate="+0%",
				pitch="+0Hz",
				proxy="http://127.0.0.1:12345",
			)
			client.save.assert_awaited_once()

	def test_default_voice_follows_the_spoken_language(self):
		with (
			patch("joymedia.services.workflows.capabilities.configured_workflow", return_value=None),
			patch("frappe.conf", frappe._dict()),
		):
			self.assertEqual("vi-VN-HoaiMyNeural", provider(text="Mềm mại như mây")["voice"])
			self.assertEqual("en-US-AriaNeural", provider(text="Soft as a cloud")["voice"])
			self.assertEqual("en-GB-SoniaNeural", provider("en-GB-SoniaNeural", text="Mềm")["voice"])

	def test_an_unreachable_operator_route_falls_back_to_the_direct_route_once(self):
		down, direct = Mock(), Mock()
		down.save = AsyncMock(side_effect=ConnectionRefusedError("proxy forward is down"))
		direct.save = AsyncMock()
		with (
			patch("joymedia.services.workflows.capabilities.configured_workflow", return_value=None),
			patch("frappe.conf", frappe._dict(joymedia_tts_proxy="http://127.0.0.1:12345")),
			patch("edge_tts.Communicate", side_effect=[down, direct]) as communicate,
			tempfile.TemporaryDirectory() as directory,
		):
			synthesize("Exact dialogue.", provider("vi-VN-HoaiMyNeural"), Path(directory) / "voice.mp3", 3)
		self.assertEqual(
			[call.kwargs["proxy"] for call in communicate.call_args_list], ["http://127.0.0.1:12345", None]
		)
		direct.save.assert_awaited_once()
