"""Keep task identity locking scoped to a run instead of scanning all live jobs."""

import frappe


def execute():
	frappe.db.add_index(
		"Generation Task",
		["generation_run", "shot", "segment_index", "pipeline_step_key"],
		index_name="generation_task_identity",
	)
