from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflow_routing import (
	automatic_planning_input_contract,
	resolve_shot_render_route,
)


def _reference(role, number):
	return {"reference_role": role, "asset_version": f"ASTV-{number:05d}"}


class TestWorkflowRouting(FrappeTestCase):
	def test_planner_keeps_multiple_characters_as_semantic_inputs(self):
		contract = automatic_planning_input_contract()
		person = next(item for item in contract if item["role"] == "person")
		self.assertTrue(person["allow_multiple"])

	@patch("joymedia.services.workflow_routing.frappe.get_doc")
	@patch("joymedia.services.workflow_resolver.get_workflow_input_contract")
	@patch("joymedia.services.generation_pipeline_service.get_pipeline_steps")
	@patch("joymedia.services.generation_pipeline_service.get_active_generation_pipeline")
	def test_promoted_pipeline_preserves_multiple_character_references_and_product(
		self, active_pipeline, pipeline_steps, input_contract, get_doc
	):
		active_pipeline.return_value = SimpleNamespace(name="PIPE-FLUX-H3")
		pipeline_steps.return_value = [
			SimpleNamespace(workflow="WF-FLUX"),
			SimpleNamespace(workflow="WF-H3"),
		]
		input_contract.return_value = [
			{"role": "person", "allow_multiple": True},
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
		self.assertEqual(["person", "person", "product"], [item["reference_role"] for item in route["references"]])
		self.assertTrue(route["requires_recomposition"])

	@patch("joymedia.services.workflow_routing.frappe.get_doc")
	@patch("joymedia.services.workflow_resolver.get_workflow_input_contract", return_value=[])
	@patch("joymedia.services.generation_pipeline_service.get_pipeline_steps")
	@patch("joymedia.services.generation_pipeline_service.get_active_generation_pipeline")
	def test_unsupported_reference_is_rejected_instead_of_dropped(
		self, active_pipeline, pipeline_steps, _input_contract, get_doc
	):
		active_pipeline.return_value = SimpleNamespace(name="PIPE-FLUX-H3")
		pipeline_steps.return_value = [SimpleNamespace(workflow="WF-FLUX"), SimpleNamespace(workflow="WF-H3")]
		get_doc.side_effect = lambda _doctype, name: SimpleNamespace(name=name)

		with self.assertRaises(frappe.ValidationError):
			resolve_shot_render_route(SimpleNamespace(name="WF-H3"), [_reference("Character", 1)])

	@patch("joymedia.services.workflow_resolver.get_workflow_input_contract")
	@patch("joymedia.services.generation_pipeline_service.get_active_generation_pipeline")
	def test_draft_route_does_not_promote_an_unconfigured_pipeline(self, active_pipeline, input_contract):
		active_pipeline.side_effect = frappe.ValidationError("No active Generation Pipeline is configured.")
		input_contract.return_value = [{"role": "person", "allow_multiple": True}]

		route = resolve_shot_render_route(SimpleNamespace(name="WF-DRAFT"), [_reference("Character", 1)])

		self.assertEqual("unpromoted_workflow", route["strategy"])
		self.assertFalse(route["generation_pipeline"])
		self.assertEqual(["person"], [item["reference_role"] for item in route["references"]])

	@patch("joymedia.services.workflow_routing.frappe.get_doc")
	@patch("joymedia.services.workflow_resolver.get_workflow_input_contract", return_value=[])
	@patch("joymedia.services.generation_pipeline_service.get_pipeline_steps")
	@patch("joymedia.services.generation_pipeline_service.get_active_generation_pipeline")
	def test_explicit_pipeline_pin_is_not_replaced_by_current_active_pipeline(
		self, active_pipeline, pipeline_steps, _input_contract, get_doc
	):
		pipeline_steps.return_value = [SimpleNamespace(workflow="WF-IMAGE"), SimpleNamespace(workflow="WF-VIDEO")]
		get_doc.side_effect = lambda doctype, name: (
			SimpleNamespace(name=name) if doctype == "Generation Pipeline" else SimpleNamespace(name=name)
		)

		route = resolve_shot_render_route(
			SimpleNamespace(name="WF-VIDEO"), [], pipeline_name="PIPE-PINNED"
		)

		self.assertEqual("PIPE-PINNED", route["generation_pipeline"])
		active_pipeline.assert_not_called()
