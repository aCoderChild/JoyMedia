from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflow_routing import (
	automatic_planning_input_contract,
	_route,
	resolve_shot_render_route,
	route_shot_references,
	strategy_for_references,
)


def _reference(role, number):
	return {"reference_role": role, "asset_version": f"ASTV-{number:05d}"}


class TestWorkflowRouting(FrappeTestCase):
	def test_planner_receives_semantic_roles_not_a_default_graph_contract(self):
		contract = automatic_planning_input_contract()
		self.assertEqual(
			["person", "product", "product_2", "environment", "reference_board"],
			[item["role"] for item in contract],
		)
		self.assertTrue(contract[-1]["allow_multiple"])

	def test_routes_against_actual_reference_capacity(self):
		cases = (
			([], "flux_keyframe_i2v"),
			([_reference("Product", 1)], "flux_keyframe_i2v"),
			([_reference("Character", 1), _reference("Product", 2)], "flux2_multireference_i2v"),
			([
				_reference("Character", 1), _reference("Product", 2), _reference("Environment", 3),
			], "flux2_multireference_i2v"),
		)
		for references, expected in cases:
			strategy, _items, _reason = strategy_for_references(references)
			self.assertEqual(expected, strategy)

	def test_two_products_force_flux2_even_with_only_three_references(self):
		strategy, items, _reason = strategy_for_references([
			_reference("Character", 1), _reference("Product", 2), _reference("Product", 3),
		])
		self.assertEqual("flux2_multireference_i2v", strategy)
		self.assertEqual(["person", "product", "product_2"], [item["reference_role"] for item in items])

	def test_overflow_is_preserved_as_reference_board(self):
		items = route_shot_references([
			_reference("Character", 1), _reference("Product", 2), _reference("Product", 3),
			_reference("Environment", 4), _reference("Product", 5), _reference("Style", 6),
		])
		self.assertEqual(
			["person", "product", "product_2", "environment", "reference_board", "reference_board"],
			[item["reference_role"] for item in items],
		)

	def test_person_and_adjacent_locations_use_flux2_with_the_destination_preserved(self):
		strategy, items, _reason = strategy_for_references([
			_reference("Character", 1), _reference("Environment", 2), _reference("Environment", 3),
		])

		self.assertEqual("flux2_multireference_i2v", strategy)
		self.assertEqual(["person", "environment", "reference_board"], [item["reference_role"] for item in items])

	def test_product_switch_uses_composition_even_for_a_simple_pair(self):
		strategy, _items, _reason = strategy_for_references(
			[_reference("Product", 1), _reference("Product", 2)],
			handoff_type="product_switch",
		)
		self.assertEqual("flux2_multireference_i2v", strategy)

	def test_existing_direct_r2v_roles_do_not_get_reclassified_as_two_products(self):
		strategy, _items, _reason = strategy_for_references([
			_reference("product_reference", 1), _reference("product_reference", 2),
		])
		self.assertEqual("direct_r2v", strategy)

	def test_character_and_environment_do_not_use_anonymous_r2v_slots(self):
		strategy, _items, _reason = strategy_for_references([
			_reference("Character", 1), _reference("Environment", 2),
		])
		self.assertEqual("flux2_multireference_i2v", strategy)

	def test_any_explicit_reference_requires_a_new_keyframe(self):
		workflow = SimpleNamespace(name="WF-I2V")
		route = _route(
			"flux_keyframe_i2v", workflow, SimpleNamespace(name="PIPE-KEYFRAME"),
			[{"asset_version": "ASTV-1", "reference_role": "keyframe_reference"}], "test",
		)
		self.assertTrue(route["requires_recomposition"])

	@patch("joymedia.services.workflow_routing.frappe.get_doc")
	@patch("joymedia.services.workflow_routing._pipeline_for")
	def test_flux2_falls_back_to_an_installed_i2v_tier(self, pipeline_for, get_doc):
		default = MagicMock(workflow_key="h3_r2v_turbo")
		fallback = SimpleNamespace(name="PIPE-FLUX2", steps=[SimpleNamespace(workflow="WF-KEY"), SimpleNamespace(workflow="WF-VIDEO")])
		pipeline_for.side_effect = [None, fallback]
		get_doc.return_value = MagicMock(name="WF-VIDEO")

		route = resolve_shot_render_route(
			default, [_reference("Character", 1), _reference("Environment", 2), _reference("Environment", 3)]
		)

		self.assertEqual("PIPE-FLUX2", route["generation_pipeline"])
		self.assertEqual(
			[("flux2_klein_multireference_keyframe", "h3_i2v_turbo"), ("flux2_klein_multireference_keyframe", None)],
			[call.args for call in pipeline_for.call_args_list],
		)
