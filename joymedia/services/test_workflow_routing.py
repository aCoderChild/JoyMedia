from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflow_routing import (
	automatic_planning_input_contract,
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
			([_reference("Character", 1), _reference("Product", 2)], "direct_r2v"),
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
