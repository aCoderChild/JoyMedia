import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflows.routing import (
	automatic_planning_input_contract,
	resolve_shot_render_route,
)


def _reference(role, number):
	return {"reference_role": role, "asset_version": f"ASTV-{number:05d}"}


class TestWorkflowRouting(FrappeTestCase):
	def test_geometry_route_requires_an_operator_mapping_and_binds_the_same_environment_as_geometry(self):
		from joymedia.services.workflows.routing import _geometry_pipeline, _map_pipeline_references

		base = SimpleNamespace(name="PIPE-BASE")
		candidate = SimpleNamespace(name="PIPE-GEOMETRY")
		image = SimpleNamespace(
			name="WF-GEOMETRY",
			output_media_type="Image",
			execution_spec={"capabilities": ["depth_guided_reference"]},
		)
		steps = {
			"PIPE-BASE": [SimpleNamespace(workflow="WF-IMAGE"), SimpleNamespace(workflow="WF-VIDEO")],
			"PIPE-GEOMETRY": [SimpleNamespace(workflow="WF-GEOMETRY"), SimpleNamespace(workflow="WF-VIDEO")],
		}
		refs = [_reference("Product", 1), {**_reference("Environment", 2), "reference_key": "room"}]
		with (
			patch(
				"joymedia.services.workflows.routing.frappe.conf",
				{"joymedia_geometry_generation_pipelines": {"PIPE-BASE": "PIPE-GEOMETRY"}},
			),
			patch.object(frappe.db, "exists", return_value=True),
			patch(
				"joymedia.services.workflows.pipeline.get_pipeline_steps",
				side_effect=lambda name: steps[name],
			),
			patch(
				"joymedia.services.workflows.routing.frappe.get_doc",
				side_effect=lambda _doctype, name: {"PIPE-GEOMETRY": candidate, "WF-GEOMETRY": image}[name],
			),
			patch(
				"joymedia.services.workflows.resolver.get_workflow_input_contract",
				return_value=[{"role": "geometry_reference", "required": True}],
			),
			patch(
				"joymedia.services.workflows.capabilities.controls",
				return_value=frozenset({"depth_guided_reference"}),
			),
		):
			self.assertEqual((candidate, image), _geometry_pipeline(base, refs))
		self.assertEqual(
			["geometry_reference", "product", "environment"],
			[
				item["reference_role"]
				for item in _map_pipeline_references(
					refs, {"geometry_reference": {}, "product": {}, "environment": {}}
				)
			],
		)

	def test_geometry_route_is_not_selected_without_an_environment_anchor(self):
		from joymedia.services.workflows.routing import _geometry_pipeline

		self.assertIsNone(_geometry_pipeline(SimpleNamespace(name="PIPE-BASE"), [_reference("Product", 1)]))

	def test_configured_geometry_pipeline_routes_a_product_scene_and_preserves_video_stage(self):
		base = SimpleNamespace(name="PIPE-BASE")
		candidate = SimpleNamespace(name="PIPE-GEOMETRY")
		image = SimpleNamespace(
			name="WF-GEOMETRY",
			output_media_type="Image",
			execution_spec={"capabilities": ["depth_guided_reference"]},
		)
		steps = {
			"PIPE-BASE": [SimpleNamespace(workflow="WF-IMAGE"), SimpleNamespace(workflow="WF-VIDEO")],
			"PIPE-GEOMETRY": [SimpleNamespace(workflow="WF-GEOMETRY"), SimpleNamespace(workflow="WF-VIDEO")],
		}
		contract = [
			{"role": "geometry_reference", "required": True},
			{"role": "product", "required": False},
			{"role": "environment", "required": False},
		]
		refs = [_reference("Product", 1), _reference("Environment", 2)]
		with (
			patch(
				"joymedia.services.workflows.routing.frappe.conf",
				{"joymedia_geometry_generation_pipelines": {"PIPE-BASE": "PIPE-GEOMETRY"}},
			),
			patch.object(frappe.db, "exists", return_value=True),
			patch(
				"joymedia.services.workflows.pipeline.get_pipeline_steps",
				side_effect=lambda name: steps[name],
			),
			patch(
				"joymedia.services.workflows.routing.frappe.get_doc",
				side_effect=lambda _doctype, name: {
					"PIPE-BASE": base,
					"PIPE-GEOMETRY": candidate,
					"WF-GEOMETRY": image,
				}[name],
			),
			patch("joymedia.services.workflows.resolver.get_workflow_input_contract", return_value=contract),
			patch(
				"joymedia.services.workflows.capabilities.controls",
				return_value=frozenset({"depth_guided_reference"}),
			),
		):
			route = resolve_shot_render_route(
				SimpleNamespace(name="WF-VIDEO"), refs, pipeline_name="PIPE-BASE"
			)
		self.assertEqual("PIPE-GEOMETRY", route["generation_pipeline"])
		self.assertEqual("WF-GEOMETRY", route["workflow"])
		self.assertEqual(
			["geometry_reference", "product", "environment"],
			[row["reference_role"] for row in route["references"]],
		)
		self.assertIn("geometry anchor", route["reason"])

	def test_endpoint_route_uses_explicit_last_frame_and_validated_sibling_pipeline(self):
		from joymedia.services.workflows.routing import _endpoint_pipeline

		base = SimpleNamespace(name="PIPE-BASE")
		candidate = SimpleNamespace(name="PIPE-ENDPOINT")
		end_video = SimpleNamespace(name="WF-END", output_media_type="Video", output_fps=24)
		base_video = SimpleNamespace(name="WF-REF", output_media_type="Video", output_fps=24)
		steps = {
			"PIPE-BASE": [SimpleNamespace(workflow="WF-IMAGE"), SimpleNamespace(workflow="WF-REF")],
			"PIPE-ENDPOINT": [SimpleNamespace(workflow="WF-IMAGE"), SimpleNamespace(workflow="WF-END")],
		}
		plan = json.dumps(
			{"shot_structure": {"subject_motion": "locomotion"}, "camera_intent": {"behavior": "tracking"}}
		)
		refs = [_reference("Character", 1), _reference("Product", 2), _reference("last_frame", 3)]
		with (
			patch(
				"joymedia.services.workflows.routing.frappe.conf",
				{"joymedia_endpoint_generation_pipelines": {"PIPE-BASE": candidate.name}},
			),
			patch.object(frappe.db, "exists", return_value=True),
			patch(
				"joymedia.services.workflows.pipeline.get_pipeline_steps",
				side_effect=lambda name: steps[name],
			),
			patch(
				"joymedia.services.workflows.routing.frappe.get_doc",
				side_effect=lambda doctype, name: {
					"PIPE-ENDPOINT": candidate,
					"WF-END": end_video,
					"WF-REF": base_video,
				}[name],
			),
			patch(
				"joymedia.services.workflows.resolver.get_workflow_input_contract",
				return_value=[
					{"role": "first_frame", "max_count": 1},
					{"role": "last_frame", "max_count": 1},
				],
			),
		):
			self.assertEqual((candidate, end_video), _endpoint_pipeline(base, refs, plan))
			self.assertIsNone(_endpoint_pipeline(base, refs[:-1], plan))
			self.assertIsNone(
				_endpoint_pipeline(
					base,
					refs,
					json.dumps(
						{
							"shot_structure": {"subject_motion": "manipulation"},
							"camera_intent": {"behavior": "tracking"},
						}
					),
				)
			)
			self.assertIsNone(
				_endpoint_pipeline(
					base,
					refs,
					json.dumps(
						{
							"shot_structure": {"subject_motion": "contact"},
							"camera_intent": {"behavior": "tracking"},
						}
					),
				)
			)
			self.assertIsNone(
				_endpoint_pipeline(
					base,
					refs,
					json.dumps(
						{
							"shot_structure": {"subject_motion": "locomotion"},
							"camera_intent": {"behavior": "locked"},
						}
					),
				)
			)
			end_video.output_fps = 30
			with self.assertRaisesRegex(ValueError, "matching FPS"):
				_endpoint_pipeline(base, refs, plan)

	def test_illustrated_characters_are_not_silently_sent_to_human_face_controls(self):
		from joymedia.services.workflows.routing import _map_pipeline_references

		with self.assertRaises(frappe.ValidationError):
			_map_pipeline_references([_reference("Character", 1)], {"person": {"allow_multiple": True}})

	def test_planner_keeps_multiple_characters_as_semantic_inputs(self):
		contract = automatic_planning_input_contract()
		person = next(item for item in contract if item["role"] == "person")
		self.assertTrue(person["allow_multiple"])

	@patch("joymedia.services.workflows.routing.frappe.get_doc")
	@patch("joymedia.services.workflows.resolver.get_workflow_input_contract")
	@patch("joymedia.services.workflows.pipeline.get_pipeline_steps")
	@patch("joymedia.services.workflows.pipeline.get_active_generation_pipeline")
	def test_promoted_pipeline_preserves_multiple_character_references_and_product(
		self, active_pipeline, pipeline_steps, input_contract, get_doc
	):
		active_pipeline.return_value = SimpleNamespace(name="PIPE-FLUX-H3")
		pipeline_steps.return_value = [
			SimpleNamespace(workflow="WF-FLUX"),
			SimpleNamespace(workflow="WF-H3"),
		]
		input_contract.return_value = [
			{"role": "character", "allow_multiple": True},
			{"role": "product", "allow_multiple": True},
		]
		get_doc.side_effect = lambda _doctype, name: SimpleNamespace(name=name)

		route = resolve_shot_render_route(
			SimpleNamespace(name="WF-H3"),
			[_reference("Character", 1), _reference("Character", 2), _reference("Product", 3)],
			handoff_type="new_scene",
		)

		self.assertEqual("promoted_linear_pipeline", route["strategy"])
		self.assertEqual("PIPE-FLUX-H3", route["generation_pipeline"])
		self.assertEqual(
			["character", "character", "product"], [item["reference_role"] for item in route["references"]]
		)
		self.assertTrue(route["requires_recomposition"])

	@patch("joymedia.services.workflows.routing.frappe.get_doc")
	@patch("joymedia.services.workflows.resolver.get_workflow_input_contract", return_value=[])
	@patch("joymedia.services.workflows.pipeline.get_pipeline_steps")
	@patch("joymedia.services.workflows.pipeline.get_active_generation_pipeline")
	def test_unsupported_reference_is_rejected_instead_of_dropped(
		self, active_pipeline, pipeline_steps, _input_contract, get_doc
	):
		active_pipeline.return_value = SimpleNamespace(name="PIPE-FLUX-H3")
		pipeline_steps.return_value = [SimpleNamespace(workflow="WF-FLUX"), SimpleNamespace(workflow="WF-H3")]
		get_doc.side_effect = lambda _doctype, name: SimpleNamespace(name=name)

		with self.assertRaises(frappe.ValidationError):
			resolve_shot_render_route(SimpleNamespace(name="WF-H3"), [_reference("Character", 1)])

	@patch("joymedia.services.workflows.resolver.get_workflow_input_contract")
	@patch("joymedia.services.workflows.pipeline.get_active_generation_pipeline")
	def test_draft_route_does_not_promote_an_unconfigured_pipeline(self, active_pipeline, input_contract):
		active_pipeline.side_effect = frappe.ValidationError("No active Generation Pipeline is configured.")
		input_contract.return_value = [{"role": "character", "allow_multiple": True}]

		route = resolve_shot_render_route(SimpleNamespace(name="WF-DRAFT"), [_reference("Character", 1)])

		self.assertEqual("unpromoted_workflow", route["strategy"])
		self.assertFalse(route["generation_pipeline"])
		self.assertEqual(["character"], [item["reference_role"] for item in route["references"]])

	@patch("joymedia.services.workflows.routing.frappe.get_doc")
	@patch("joymedia.services.workflows.resolver.get_workflow_input_contract", return_value=[])
	@patch("joymedia.services.workflows.pipeline.get_pipeline_steps")
	@patch("joymedia.services.workflows.pipeline.get_active_generation_pipeline")
	def test_explicit_pipeline_pin_is_not_replaced_by_current_active_pipeline(
		self, active_pipeline, pipeline_steps, _input_contract, get_doc
	):
		pipeline_steps.return_value = [
			SimpleNamespace(workflow="WF-IMAGE"),
			SimpleNamespace(workflow="WF-VIDEO"),
		]
		get_doc.side_effect = lambda doctype, name: SimpleNamespace(name=name)

		route = resolve_shot_render_route(SimpleNamespace(name="WF-VIDEO"), [], pipeline_name="PIPE-PINNED")

		self.assertEqual("PIPE-PINNED", route["generation_pipeline"])
		active_pipeline.assert_not_called()
