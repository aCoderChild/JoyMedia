import json
import unittest
from pathlib import Path

from joymedia.services.workflows.audit import api_graph
from joymedia.services.workflows.schema import graph_schema_errors


class TestGraphSchema(unittest.TestCase):
	def setUp(self):
		self.info = {
			"Loader": {"input": {"required": {"model": [["installed.safetensors"]]}}, "output": ["MODEL"]},
			"Decode": {
				"input": {"required": {"samples": ["LATENT"], "count": ["INT", {"min": 1, "max": 124}]}},
				"output": ["IMAGE"],
			},
		}

	def test_reports_missing_models_and_wrong_socket_types(self):
		graph = {
			"load": {"class_type": "Loader", "inputs": {"model": "missing.safetensors"}},
			"decode": {"class_type": "Decode", "inputs": {"samples": ["load", 0], "count": 125}},
		}
		errors = graph_schema_errors(graph, self.info)
		self.assertEqual(len(errors), 3)
		self.assertTrue(any("expected LATENT, got MODEL" in e for e in errors))

	def test_bound_file_placeholders_are_not_model_availability_errors(self):
		graph = {"load": {"class_type": "Loader", "inputs": {"model": "placeholder"}}}
		self.assertEqual([], graph_schema_errors(graph, self.info, bound_inputs=[("load", "model")]))

	def test_bad_output_index_and_missing_required_input(self):
		graph = {
			"load": {"class_type": "Loader", "inputs": {"model": "installed.safetensors"}},
			"decode": {"class_type": "Decode", "inputs": {"samples": ["load", 3]}},
		}
		self.assertEqual(len(graph_schema_errors(graph, self.info)), 2)

	def test_optional_null_and_v3_inputs_remain_server_validated(self):
		info = {"Dynamic": {"input": {"optional": {"image": ["IMAGE"]}}, "output": []}}
		graph = {
			"x": {
				"class_type": "Dynamic",
				"inputs": {"image": None, "images.image_1": "server-validated-value"},
			}
		}
		self.assertEqual([], graph_schema_errors(graph, info))

	def test_valid_socket_types_do_not_allow_a_dependency_cycle(self):
		info = {"Pass": {"input": {"required": {"image": ["IMAGE"]}}, "output": ["IMAGE"]}}
		graph = {
			"a": {"class_type": "Pass", "inputs": {"image": ["b", 0]}},
			"b": {"class_type": "Pass", "inputs": {"image": ["a", 0]}},
		}
		self.assertTrue(any("Dependency cycle" in error for error in graph_schema_errors(graph, info)))

	def test_flattened_dynamic_input_satisfies_parent_and_polymorphic_socket(self):
		info = {
			"Math": {"input": {"required": {"values": ["COMFY_AUTOGROW_V3"]}}, "output": ["INT"]},
			"Switch": {
				"input": {"required": {"on_true": ["COMFY_MATCHTYPE_V3"]}},
				"output": ["COMFY_MATCHTYPE_V3"],
			},
		}
		graph = {
			"m": {"class_type": "Math", "inputs": {"values.a": 5}},
			"s": {"class_type": "Switch", "inputs": {"on_true": ["m", 0]}},
		}
		self.assertEqual([], graph_schema_errors(graph, info))

	def test_ui_seed_control_does_not_become_prompt_text(self):
		info = {"Sampler": {"input": {"required": {"seed": ["INT"], "prompt": ["STRING"]}}, "output": []}}
		export = {"nodes": [{"id": 1, "type": "Sampler", "widgets_values": [42, "randomize", "music only"]}]}
		self.assertEqual({"seed": 42, "prompt": "music only"}, api_graph(export, info)["1"]["inputs"])

	def test_music_and_foley_have_separate_conditioning_contracts(self):
		graphs = Path(__file__).resolve().parents[2] / "workflow_adapters" / "graphs"
		music = json.loads((graphs / "mmaudio_bgm.json").read_text())["music"]["inputs"]
		foley = json.loads((graphs / "mmaudio_video_to_audio.json").read_text())["92"]["inputs"]
		self.assertNotIn("images", music)
		self.assertTrue(music["mask_away_clip"])
		self.assertNotIn("music", music["negative_prompt"])
		self.assertIn("music", foley["negative_prompt"])
		self.assertIn("images", foley)

	def test_h3_rounds_authored_dimensions_to_native_grid(self):
		from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS, _h3_spec
		from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter

		graph = json.loads((GRAPHS / "minimax_h3_i2v.json").read_text())
		adapter = GenericComfyUIAdapter()
		adapter.execution_spec = _h3_spec()
		resolved = adapter.prepare_execution(
			graph, seed=5, width=720, height=1280, fps=24, frame_count=96, output_prefix="test"
		)
		self.assertEqual(
			(736, 1280), (resolved["104"]["inputs"]["width"], resolved["104"]["inputs"]["height"])
		)
		self.assertEqual(4, resolved["111"]["inputs"]["value"])
		self.assertEqual(
			{"model": ["122", 0], "shift_video": 12.0, "shift_audio": 3.0}, resolved["sigma_shift"]["inputs"]
		)
		for width, height, expected in [(720, 900, (736, 896)), (1680, 720, (1696, 736))]:
			with self.subTest(width=width, height=height):
				resolved = adapter.prepare_execution(
					graph, seed=5, width=width, height=height, fps=24, frame_count=96, output_prefix="test"
				)
				self.assertEqual(
					expected, (resolved["104"]["inputs"]["width"], resolved["104"]["inputs"]["height"])
				)
