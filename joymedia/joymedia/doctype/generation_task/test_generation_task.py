# Copyright (c) 2026, JoyMedia and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from .generation_task import GenerationTask


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestGenerationTask(IntegrationTestCase):
	"""
	Integration tests for GenerationTask.
	Use this class for testing interactions between multiple components.
	"""

	def test_prepared_task_execution_fields_cannot_change(self):
		task = GenerationTask({
			"doctype": "Generation Task",
			"name": "TASK-TEST",
			"generation_run": "RUN-1",
			"shot": "SHOT-1",
			"workflow": "WF-1",
			"prompt_text": "Original prompt",
			"prompt_hash": "hash-1",
			"segment_index": 1,
			"segment_frame_count": 10,
			"depends_on_task": None,
		})
		task.prompt_text = "Changed prompt"
		previous = frappe._dict({
			"status": "Ready",
			"generation_run": "RUN-1",
			"shot": "SHOT-1",
			"workflow": "WF-1",
			"prompt_text": "Original prompt",
			"prompt_hash": "hash-1",
			"segment_index": 1,
			"segment_frame_count": 10,
			"depends_on_task": None,
		})
		with patch.object(task, "is_new", return_value=False), patch.object(
			task, "get_doc_before_save", return_value=previous
		), self.assertRaises(frappe.ValidationError):
			task._validate_execution_immutability()

	def test_input_snapshot_preserves_order(self):
		rows = [
			frappe._dict(input_role="product_reference", asset_version="ASSET-1"),
			frappe._dict(input_role="product_reference", asset_version="ASSET-2"),
		]
		self.assertEqual(
			[
				("product_reference", "ASSET-1", ""),
				("product_reference", "ASSET-2", ""),
			],
			GenerationTask._normalized_inputs(rows),
		)

	def test_chained_task_rejects_workflow_without_first_frame_continuation(self):
		task = GenerationTask({
			"doctype": "Generation Task",
			"name": "TASK-CHILD",
			"generation_run": "RUN-1",
			"shot": "SHOT-1",
			"workflow": "WF-R2V",
			"prompt_text": "Continue the architectural shot.",
			"prompt_hash": "hash-1",
			"segment_index": 2,
			"segment_frame_count": 37,
			"depends_on_task": "TASK-PARENT",
		})
		shot = frappe._dict(name="SHOT-1", media_project="PROJECT-1")
		project = frappe._dict(name="PROJECT-1")
		run = frappe._dict(name="RUN-1", media_project="PROJECT-1", workflow="WF-R2V")
		workflow = frappe._dict(name="WF-R2V", frame_count=124, bindings=[])

		with (
			patch(
				"joymedia.joymedia.doctype.generation_task.generation_task.frappe.db.exists",
				return_value=True,
			),
			patch(
				"joymedia.joymedia.doctype.generation_task.generation_task.frappe.get_doc",
				side_effect=[shot, project, run, workflow],
			),
			patch(
				"joymedia.services.workflow_resolver.workflow_supports_continuation",
				return_value=False,
			),
			self.assertRaises(frappe.ValidationError),
		):
			task._validate_execution_references()
