from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.planning.video_plan import _route_and_validate_plan_shot


class TestVideoPlanRoute(TestCase):
	def test_routed_reference_role_is_validated_against_workflow_contract(self):
		shot = {
			"shot_number": 1,
			"references": [{"reference_key": "pack", "usage_role": "Product"}],
		}
		references = {"pack": frappe._dict(reference_role="Product", asset_version="ASTV-TEST")}
		route = {
			"strategy": "promoted_linear_pipeline",
			"workflow": "WF-TEST",
			"generation_pipeline": None,
			"references": [
				{"reference_key": "pack", "reference_role": "Product", "asset_version": "ASTV-TEST"}
			],
			"reason": "test",
			"requires_recomposition": False,
		}
		contract = [{"role": "product", "min_count": 1, "max_count": 1}]
		with (
			patch("joymedia.services.workflows.routing.resolve_shot_render_route", return_value=route),
			patch("joymedia.services.workflows.resolver.get_workflow_input_contract", return_value=contract),
			patch.object(frappe, "get_doc", return_value=frappe._dict(name="WF-TEST")),
		):
			_route_and_validate_plan_shot(shot, references, frappe._dict(name="WF-TEST"))

		self.assertEqual([{"reference_key": "pack", "usage_role": "Product"}], shot["references"])
