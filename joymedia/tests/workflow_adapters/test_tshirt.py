import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.patches.register_tshirt_pipeline import GRAPH, execution_spec
from joymedia.services.editing.delivery import delivery_contract, transform_delivery
from joymedia.services.planning.camera import camera_intent, camera_plan
from joymedia.services.planning.plan_parsing import _normalized_motion_plan


class TestTShirtWorkflow(TestCase):
	def test_native_graph_uses_coupled_av_sampler_and_lossless_last_frame(self):
		g = json.loads(GRAPH.read_text())
		self.assertEqual(g["14"]["class_type"], "SamplerCustomAdvanced")
		self.assertEqual(g["17"]["inputs"]["sampler_name"], "res_multistep")
		self.assertTrue(g["126"]["inputs"]["value"])
		self.assertEqual(g["125"]["inputs"]["value"], 8)
		self.assertEqual(g["23"]["inputs"]["samples"], g["10"]["inputs"]["samples"])
		self.assertEqual(g["91"]["inputs"]["audio"], ["23", 0])
		self.assertEqual(g["last_image"]["inputs"]["batch_index"], 123)
		self.assertEqual(execution_spec()["outputs"]["last_frame"]["node_key"], "save_last_image")

	def test_camera_intent_is_preserved_as_structured_data(self):
		intent = {"behavior": "tracking_backward", "allow_reframe": True}
		p = _normalized_motion_plan(
			{"actions": [{"start": 0, "end": 5, "action": "Walk normally."}], "camera_intent": intent},
			5,
			"Walk normally.",
		)
		self.assertEqual(p["camera_intent"], intent)
		result = camera_plan(frappe._dict(shot_number=1, motion_plan_json=p), {})
		self.assertEqual(result["behavior"], "tracking_backward")
		self.assertIn("real-time", result["direction"])

	def test_explicit_static_preservation_overrides_a_tracking_intent(self):
		p = {
			"camera_motion": "locked",
			"camera_intent": {"behavior": "tracking_backward", "allow_reframe": True},
		}
		self.assertEqual(camera_plan(frappe._dict(motion_plan_json=p), {})["behavior"], "locked")

	def test_multiple_or_arbitrary_camera_behaviors_are_rejected(self):
		for value in [
			{"behavior": "orbit and track"},
			{"behavior": "push_in", "allow_reframe": "yes"},
			{"behavior": "push_in", "shell": "bad"},
		]:
			with self.assertRaises(ValueError):
				camera_intent(value)

	def test_ordinary_push_in_keeps_the_crop_limit(self):
		p = {"camera_intent": {"behavior": "push_in"}}
		s = frappe._dict(motion_plan_json=p)
		self.assertEqual(camera_plan(s, {})["behavior"], "locked")
		r = camera_plan(
			s, {}, framing_safety={"status": "assessed", "complete": True, "bounds": [0.2, 0.2, 0.8, 0.8]}
		)
		self.assertIn("at most 2 percent", r["direction"])

	def test_delivery_preserves_requested_aspect_even_with_legacy_portrait_defaults(self):
		for geometry, expected in [
			((1280, 720), (2560, 1440)),
			((720, 900), (1440, 1800)),
			((720, 720), (1440, 1440)),
		]:
			profile = {"width": geometry[0], "height": geometry[1], "fps": 24}
			for declaration in [
				{"width": 1440, "height": 2560, "fps": 24},
				{"short_edge": 1440, "fps": 24},
				{"short_edge": 1440, "fps": 24, "temporal_fit": "preserve_endpoints"},
			]:
				contract = delivery_contract({"execution_spec": {"delivery": declaration}}, profile)
				self.assertEqual(expected, (contract["width"], contract["height"]))

	def test_delivery_rejects_arbitrary_filters_and_frame_interpolation(self):
		self.assertIsNone(delivery_contract({"execution_spec": {}}))
		with self.assertRaises(ValueError):
			delivery_contract({"execution_spec": {"delivery": {"command": "anything"}}})
		with self.assertRaisesRegex(ValueError, "temporal_fit"):
			delivery_contract({"execution_spec": {"delivery": {"temporal_fit": "interpolate"}}})
		c = delivery_contract({"execution_spec": execution_spec()}, {"width": 720, "height": 1280, "fps": 24})
		self.assertEqual(c["fps"], 24)
		self.assertEqual(c["audio_sample_rate"], 44100)
		with self.assertRaises(ValueError):
			transform_delivery("a", "b", {"fps": 60}, c)

	def test_real_ffmpeg_delivery_preserves_frames_and_resamples_audio(self):
		with TemporaryDirectory() as tmp:
			src = Path(tmp) / "source.mp4"
			out = Path(tmp) / "master.mp4"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-f",
					"lavfi",
					"-i",
					"testsrc2=size=64x128:rate=24:duration=1",
					"-f",
					"lavfi",
					"-i",
					"sine=frequency=440:sample_rate=48000:duration=1",
					"-c:v",
					"libx264",
					"-pix_fmt",
					"yuv420p",
					"-c:a",
					"aac",
					"-shortest",
					str(src),
				],
				check=True,
			)
			c = delivery_contract(
				{
					"execution_spec": {
						"delivery": {
							"width": 144,
							"height": 256,
							"fps": 24,
							"temporal_fit": "preserve_endpoints",
						}
					}
				}
			)
			transform_delivery(src, out, {"width": 64, "height": 128, "fps": 24}, c)
			streams = json.loads(
				subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)])
			)["streams"]
			v = next(s for s in streams if s["codec_type"] == "video")
			a = next(s for s in streams if s["codec_type"] == "audio")
			self.assertEqual(
				(v["width"], v["height"], v["nb_frames"], v["r_frame_rate"]), (144, 256, "24", "24/1")
			)
			self.assertEqual((a["sample_rate"], a["channels"]), ("44100", 2))

	def test_project_pin_does_not_replace_the_global_pipeline(self):
		from joymedia.services.workflows.pipeline import get_pinned_generation_pipeline

		conf = frappe._dict(joymedia_project_generation_pipelines={"case": "PIPE-case"})
		with (
			patch.object(frappe.local, "conf", conf),
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_doc", return_value=frappe._dict(name="PIPE-case")),
			patch("joymedia.services.workflows.pipeline.get_pipeline_steps", return_value=[]),
		):
			self.assertIsNone(get_pinned_generation_pipeline("other"))
			self.assertEqual(get_pinned_generation_pipeline("case").name, "PIPE-case")

	def test_human_reference_does_not_receive_mascot_skin_palette(self):
		from joymedia.services.planning.prompts import _character_names

		shot = frappe._dict(references=[{"reference_role": "Person", "asset_version": "person"}])
		project = frappe._dict(references=[{"asset_version": "person", "label": "model"}])
		with (
			patch("joymedia.services.planning.prompts.cast_name", return_value="the male model"),
			patch("joymedia.services.keyframes.overlay.describe_colours", return_value="cream") as palette,
		):
			self.assertEqual(_character_names(shot, project), ["the male model"])
			palette.assert_not_called()

	def test_review_only_composition_does_not_sync_an_unselected_take(self):
		from joymedia.services.generation import orchestrator as o

		run = frappe._dict(
			name="run",
			media_project="project",
			execution_scope_json="{}",
			project_snapshot_json='{"shots":[{"shot":"shot"}]}',
		)
		with (
			patch.object(o.frappe, "get_all", side_effect=[["shot"], [frappe._dict(status="Completed")]]),
			patch.object(o, "_is_keyframe_run", return_value=False),
			patch.object(o, "_keeps_selected_output", return_value=False),
			patch("joymedia.services.consistency.retention.needs_candidate_review", return_value=False),
			patch.object(o, "compose_shot_segments", return_value="candidate"),
			patch.object(o.frappe.db, "get_value", return_value=None),
			patch("joymedia.services.editing.timeline.sync_timeline_source_for_shot") as sync,
		):
			o._finalize_completed_shots(run)
			sync.assert_not_called()
