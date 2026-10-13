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


class TestSetShotReferences(FrappeTestCase):
	def setUp(self):
		super().setUp()
		from joymedia.services.e2e_setup import _generate_image_bytes
		from joymedia.services.test_timeline_editor import _create_workflow

		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc({
			"doctype": "Media Project", "project_name": "Shot Refs", "workflow": _create_workflow(),
			"total_duration_seconds": 2, "delivery_preset": "Landscape",
		}).insert(ignore_permissions=True)
		asset = frappe.get_doc({
			"doctype": "Media Asset", "asset_name": "Hero", "media_type": "Image", "asset_category": "Product",
			"asset_scope": "Library",
		}).insert(ignore_permissions=True)
		file_doc = frappe.get_doc({
			"doctype": "File", "file_name": "hero.png", "content": _generate_image_bytes(), "is_private": 1,
			"attached_to_doctype": "Media Asset", "attached_to_name": asset.name,
		}).insert(ignore_permissions=True)
		self.version = frappe.get_doc({
			"doctype": "Asset Version", "media_asset": asset.name, "file": file_doc.file_url, "source": "Uploaded",
		}).insert(ignore_permissions=True)
		self.project.append("selected_media", {
			"reference_key": "hero", "asset_version": self.version.name, "reference_role": "Product", "label": "Hero",
		})
		self.project.save(ignore_permissions=True)
		self.shot = frappe.get_doc({
			"doctype": "Shot", "media_project": self.project.name, "shot_number": 1, "generation_prompt": "A scene.",
			"duration_seconds": 2.0,
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_assignment_replaces_the_scene_references_and_clears_approval(self):
		self.project.db_set("storyboard_approval_status", "Approved")
		storyboard.set_project_shot_references(self.project.name, self.shot.name, '["hero"]')

		rows = frappe.get_doc("Shot", self.shot.name).generation_inputs
		self.assertEqual([("Product", self.version.name)], [(r.reference_role, r.asset_version) for r in rows])
		self.assertEqual(
			"Ready for Review", frappe.db.get_value("Media Project", self.project.name, "storyboard_approval_status")
		)
		storyboard.set_project_shot_references(self.project.name, self.shot.name, "[]")
		self.assertEqual([], frappe.get_doc("Shot", self.shot.name).generation_inputs)

	def test_unknown_reference_key_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			storyboard.set_project_shot_references(self.project.name, self.shot.name, '["ghost"]')
