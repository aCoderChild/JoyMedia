import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.generation import guided
from joymedia.workflow_adapters.comfyui_generic import _transform_value


class TestGuidedControls(TestCase):
	def workflow(self):
		return frappe._dict(output_fps=24, bindings=[frappe._dict(binding_key=role, required_input_role=role,
			value_type="File Path", accepted_media_type=kind, required=required, allow_multiple=0)
			for role, kind, required in [("control_video", "Video", 1), ("control_mask", "Video", 0), ("identity_reference", "Image", 0)]])

	def test_bad_role_inputs_are_rejected_before_any_path_is_read(self):
		for inputs in [None, [], {}, {"control_video": "V", "arbitrary_path": "/tmp/x"}]:
			with self.subTest(inputs=inputs), patch.object(guided, "_control_path") as path:
				with self.assertRaises(ValueError):
					guided.validate_controls(frappe._dict(), self.workflow(), inputs, 72)
				path.assert_not_called()

	def test_short_wrong_rate_and_misaligned_mask_fail_before_generation(self):
		base = {"width": 480, "height": 832, "fps": 24, "frames": 72}
		for probes, inputs in [
			([{**base, "frames": 71}], {"control_video": "V"}),
			([{**base, "fps": 16}], {"control_video": "V"}),
			([base, {**base, "width": 832}], {"control_video": "V", "control_mask": "M"}),
			([base, {**base, "frames": 73}], {"control_video": "V", "control_mask": "M"}),
		]:
			with patch.object(guided, "_control_path", return_value="/owned.mp4"), patch.object(guided, "_probe", side_effect=probes), patch.object(frappe.db, "get_value", side_effect=lambda dt, *args, **kwargs: frappe._dict(media_asset="A", content_hash="digest") if dt == "Asset Version" else "Video"):
				with self.assertRaises(ValueError):
					guided.validate_controls(frappe._dict(), self.workflow(), inputs, 72)

	def test_frame_padding_never_undershoots_requested_frames(self):
		for multiple in [4, 8, 17]:
			for offset in range(multiple):
				for value in range(1, 180):
					result = _transform_value({"transform": "ceil_to_multiple", "multiple": multiple, "offset": offset}, value, {})
					self.assertGreaterEqual(result, value)
					self.assertLess(result - value, multiple)
					self.assertEqual((result - offset) % multiple, 0)

	def test_trial_graph_has_no_brand_or_actor_specific_negative_prompt(self):
		path = Path(frappe.get_app_path("joymedia", "workflow_adapters", "graphs", "wan_vace_guided.json"))
		config = json.loads(path.read_text())
		for forbidden in ["shera", "bear", "tissue", "human fingers"]:
			self.assertNotIn(forbidden, config["graph"]["negative"]["inputs"]["text"].lower())
		self.assertEqual({"control_video", "control_mask", "identity_reference"}, {b["required_input_role"] for b in config["bindings"] if b.get("required_input_role")})

	def test_unknown_library_ownership_uses_project_access_guard(self):
		version = frappe._dict(media_asset="A", file="/private/source", content_hash="x")
		parent = frappe._dict(asset_scope="Library", media_project=None, owner="another@example.test", status="Active")
		with patch.object(frappe, "get_doc", side_effect=[version, parent]), patch.object(guided, "_project_asset_path", side_effect=frappe.PermissionError) as access:
			with self.assertRaises(frappe.PermissionError):
				guided._control_path(frappe._dict(owner="owner@example.test"), "V")
			access.assert_called_once()

	def test_stale_candidate_cannot_replace_a_new_selection(self):
		from unittest.mock import MagicMock

		state = {"status": "Completed", "asset_version": "candidate"}
		run = frappe._dict(execution_scope_json=json.dumps({"shot_names": ["S"], "expected_take": "original"}))
		shot = frappe._dict(name="S", selected_output_asset_version="newer", reload=MagicMock())
		with patch.object(guided, "guided_candidate_status", return_value=state), patch.object(frappe, "get_doc", return_value=run), patch("joymedia.services.generation.takes._project_shot", return_value=(frappe._dict(name="P"), shot)), patch.object(frappe.db, "sql"), patch("joymedia.services.generation.takes.select_scene_take") as select:
			with self.assertRaises(frappe.ValidationError):
				guided.use_guided_candidate("P", "R", "original")
			select.assert_not_called()

	def test_only_the_frozen_original_can_be_replaced_by_explicit_selection(self):
		from unittest.mock import MagicMock

		state = {"status": "Completed", "asset_version": "candidate"}
		run = frappe._dict(execution_scope_json=json.dumps({"shot_names": ["S"], "expected_take": "original", "plan_signature": "approved"}))
		shot = frappe._dict(name="S", selected_output_asset_version="original", reload=MagicMock())
		with patch.object(guided, "guided_candidate_status", return_value=state), patch.object(frappe, "get_doc", return_value=run), patch("joymedia.services.generation.takes._project_shot", return_value=(frappe._dict(name="P"), shot)), patch.object(frappe.db, "sql"), patch("joymedia.services.planning.signature.compute_plan_signature", return_value="changed"), patch("joymedia.services.generation.takes.select_scene_take") as select:
			with self.assertRaises(frappe.ValidationError):
				guided.use_guided_candidate("P", "R", "original")
			select.assert_not_called()

	def test_edit_hole_is_removed_from_conditioning_but_original_is_retained_for_output(self):
		path = Path(frappe.get_app_path("joymedia", "workflow_adapters", "graphs", "wan_vace_guided.json"))
		config = json.loads(path.read_text())
		graph = config["graph"]
		conditions = config["execution_spec"]["conditional_inputs"]
		control = next(r for r in conditions if r["target"] == {"node_key": "conditioning", "input_name": "control_video"})
		self.assertEqual(control["when_present"], ["inpaint_guide", 0])
		self.assertEqual(control["when_absent"], ["guide", 0])
		self.assertEqual(graph["inpaint_guide"]["inputs"]["source"], ["neutral_hole", 0])
		self.assertEqual(graph["neutral_hole"]["inputs"]["color"], 0x808080)
		self.assertEqual(graph["masked_result"]["inputs"]["destination"], ["original_video", 0])
		self.assertEqual(graph["masked_result"]["inputs"]["source"], ["frames", 0])

	def test_masked_finishing_keeps_original_resolution_for_labels(self):
		path = Path(frappe.get_app_path("joymedia", "workflow_adapters", "graphs", "wan_vace_guided.json"))
		graph = json.loads(path.read_text())["graph"]
		self.assertTrue(graph["masked_result"]["inputs"]["resize_source"])
		self.assertEqual(graph["original_video"]["inputs"]["custom_width"], 0)
		self.assertEqual(graph["original_video"]["inputs"]["custom_height"], 0)
		self.assertEqual(graph["masked_result"]["inputs"]["mask"], ["original_mask_channel", 0])

	def test_original_resolution_loaders_share_roles_without_requesting_duplicate_assets(self):
		from joymedia.services.workflows.resolver import get_workflow_input_contract

		path = Path(frappe.get_app_path("joymedia", "workflow_adapters", "graphs", "wan_vace_guided.json"))
		config = json.loads(path.read_text())
		workflow = frappe._dict(bindings=[frappe._dict(b) for b in config["bindings"]])
		contract = {row["role"]: row for row in get_workflow_input_contract(workflow)}
		self.assertEqual(contract["control_video"]["min_count"], 1)
		self.assertEqual(contract["identity_reference"]["min_count"], 1)

	def test_reference_alpha_is_flattened_and_aspect_is_padded_before_model_conditioning(self):
		path = Path(frappe.get_app_path("joymedia", "workflow_adapters", "graphs", "wan_vace_guided.json"))
		graph = json.loads(path.read_text())["graph"]
		self.assertEqual(graph["conditioning"]["inputs"]["reference_image"], ["identity_fit", 0])
		self.assertEqual(graph["identity_fit"]["class_type"], "ResizeAndPadImage")
		self.assertEqual(graph["identity_fit"]["inputs"]["padding_color"], "white")
		self.assertEqual(graph["identity_white"]["inputs"]["color"], 0xFFFFFF)
		self.assertEqual(graph["identity_opacity"]["inputs"]["mask"], ["identity", 1])

	def test_disabled_deployment_does_not_resolve_or_queue_a_model(self):
		with patch.dict(frappe.conf, {"joymedia_guided_video_enabled": False}), patch.object(frappe, "get_doc") as get_doc:
			with self.assertRaises(ValueError):
				guided._workflow()
			get_doc.assert_not_called()

	def test_explicit_candidate_selection_uses_the_exact_persisted_take(self):
		from unittest.mock import MagicMock

		state = {"status": "Completed", "asset_version": "candidate"}
		run = frappe._dict(execution_scope_json=json.dumps({"shot_names": ["S"], "expected_take": "original", "plan_signature": "approved"}))
		shot = frappe._dict(name="S", selected_output_asset_version="original", reload=MagicMock())
		with patch.object(guided, "guided_candidate_status", return_value=state), patch.object(frappe, "get_doc", return_value=run), patch("joymedia.services.generation.takes._project_shot", return_value=(frappe._dict(name="P"), shot)), patch.object(frappe.db, "sql"), patch("joymedia.services.planning.signature.compute_plan_signature", return_value="approved"), patch("joymedia.services.generation.takes.scene_takes", return_value=[frappe._dict(name="original"), frappe._dict(name="candidate")]), patch("joymedia.services.generation.takes.select_scene_take", return_value={"selected": "candidate"}) as select:
			self.assertEqual(guided.use_guided_candidate("P", "R", "original"), {"selected": "candidate"})
			select.assert_called_once_with("P", "S", 2)
