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
