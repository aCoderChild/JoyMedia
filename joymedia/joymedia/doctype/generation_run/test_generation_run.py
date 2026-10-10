import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.project_context import build_project_snapshot


class IntegrationTestGenerationRun(FrappeTestCase):
	def setUp(self):
		super().setUp()
		from joymedia.joymedia.doctype.media_project.test_media_project import _ensure_workflow

		self.workflow = _ensure_workflow()
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Immutable Run Test",
				"product_name": "Test Product",
				"video_idea": "Create an immutable run test.",
				"total_duration_seconds": 5,
				"delivery_preset": "Landscape",
				"delivery_width": 1920,
				"delivery_height": 1080,
				"generation_mode": "Multi-shot",
				"workflow": self.workflow,
			}
		).insert(ignore_permissions=True)
		self.snapshot, self.snapshot_hash = build_project_snapshot(self.project)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _insert_run(self):
		return frappe.get_doc(
			{
				"doctype": "Generation Run",
				"media_project": self.project.name,
				"workflow": self.workflow,
				"project_snapshot_json": self.snapshot,
				"project_snapshot_hash": self.snapshot_hash,
				"requested_by": "Administrator",
				"status": "Draft",
			}
		).insert(ignore_permissions=True)

	def test_execution_identity_and_snapshot_are_immutable(self):
		run = self._insert_run()
		run.requested_by = "Guest"
		with self.assertRaises(frappe.ValidationError):
			run.save(ignore_permissions=True)

	def test_snapshot_hash_is_validated(self):
		run = self._insert_run()
		run.project_snapshot_hash = "0" * 64
		with self.assertRaises(frappe.ValidationError):
			run.save(ignore_permissions=True)
