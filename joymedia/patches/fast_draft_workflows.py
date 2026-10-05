import frappe

from .register_minimax_h3_sato_workflows import CONTINUATION
from .register_minimax_h3_workflows import WORKFLOW_SPECS, _register_workflow


def _spec(source_key, **changes):
	return {**next(spec for spec in WORKFLOW_SPECS if spec["workflow_key"] == source_key), **changes}


def execute():
	# Fast draft mode: the 4/8-step turbo models render ~4x faster at full resolution.
	# Draft scenes' own audio is replaced by the film's soundtrack, so the turbo
	# continuation's weaker audio does not reach the film.
	turbo = _register_workflow(_spec("h3_r2v_turbo"))
	_register_workflow(_spec("h3_i2v_production", filename="minimax_h3_i2v_turbo.json", workflow_key="h3_i2v_turbo"))
	continuation = _register_workflow(
		{**CONTINUATION, "filename": "minimax_h3_sato_continuation_turbo.json", "workflow_key": "h3_sato_continuation_turbo"}
	)
	frappe.db.set_value("Generation Workflow", turbo, "continuation_workflow", continuation, update_modified=False)
