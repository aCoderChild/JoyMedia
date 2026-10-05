import frappe

from .register_minimax_h3_sato_workflows import CONTINUATION, GENERATION
from .register_minimax_h3_workflows import _register_workflow


def execute():
	# The Sato graphs ran a turbo LoRA at 7 steps, which turned their audio into
	# low rumble. They now run the full model at 20 steps, like Image-to-Video.
	continuation = _register_workflow(CONTINUATION)
	generation = _register_workflow(GENERATION)
	starters = [generation] + [
		frappe.db.get_value(
			"Generation Workflow", {"workflow_key": key}, "name", order_by="version_number desc, modified desc"
		)
		for key in ("h3_r2v_production", "h3_r2v_turbo")
	]
	for name in filter(None, starters):
		frappe.db.set_value("Generation Workflow", name, "continuation_workflow", continuation, update_modified=False)
