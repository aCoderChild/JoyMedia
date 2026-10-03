import frappe

from joymedia.workflow_adapters.minimax_h3_profiles import R2V_MAX_FRAMES


def execute():
	frappe.db.set_value(
		"Generation Workflow",
		{"adapter_key": "minimax_h3_r2v"},
		"frame_count",
		R2V_MAX_FRAMES,
		update_modified=False,
	)
