from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.api import storyboard


class TestStoryboardReferenceContracts(FrappeTestCase):
	def _validate(self, shots, mapped_roles, contract, route_error=None):
		project = frappe._dict(name="P", workflow="W", generation_pipeline="PL")
		pipeline = frappe._dict(steps=[frappe._dict(workflow="W1")])

		def get_doc(doctype, name=None):
			return {"Shot": shots[name] if doctype == "Shot" else None, "Generation Pipeline": pipeline}.get(
				doctype, frappe._dict(name=name)
			)

		route = {"generation_pipeline": "PL", "references": []}
		with patch.object(storyboard.frappe, "get_all", return_value=list(shots)), patch.object(
			storyboard.frappe, "get_doc", side_effect=get_doc
		), patch(
			"joymedia.services.workflow_routing.resolve_shot_render_route",
			side_effect=route_error, return_value=route,
		), patch(
			"joymedia.services.generation_orchestrator._pipeline_reference_inputs", return_value=mapped_roles
		), patch("joymedia.services.workflow_resolver.get_workflow_input_contract", return_value=contract):
			storyboard._validate_shot_reference_contracts(project)

	def _shot(self, mode="New Scene", number=1):
		return frappe._dict(
			shot_name="Shot", name="S", handoff_type="", continuity_mode=mode, shot_number=number, generation_inputs=[]
		)

	def test_missing_required_role_blocks_approval(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate({"S": self._shot()}, {}, [{"role": "person", "required": True}])

	def test_assigned_required_role_passes(self):
		self._validate({"S": self._shot()}, {"person": ["AV"]}, [{"role": "person", "required": True}])

	def test_continuing_shot_needs_no_keyframe_reference(self):
		self._validate({"S": self._shot("Continue", 2)}, {}, [{"role": "person", "required": True}])

	def test_every_shot_problem_is_reported_together(self):
		shots = {"A": self._shot(), "B": self._shot()}
		shots["A"].shot_name, shots["B"].shot_name = "First", "Second"
		with self.assertRaises(frappe.ValidationError) as caught:
			self._validate(shots, {}, [{"role": "person", "required": True}])
		self.assertIn("First", str(caught.exception))
		self.assertIn("Second", str(caught.exception))
