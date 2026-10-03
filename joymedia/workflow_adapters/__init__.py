import frappe

from .minimax_h3 import MiniMaxH3WorkflowAdapter
from .minimax_h3_sato import MiniMaxH3SatoAdapter
from .minimax_h3_profiles import (
	MiniMaxH3ImageToVideoAdapter,
	MiniMaxH3ReferenceToVideoAdapter,
)


ADAPTERS = {
	"minimax_h3": MiniMaxH3WorkflowAdapter,
	"minimax_h3_i2v": MiniMaxH3ImageToVideoAdapter,
	"minimax_h3_r2v": MiniMaxH3ReferenceToVideoAdapter,
	"minimax_h3_sato": MiniMaxH3SatoAdapter,
}


def get_workflow_adapter(workflow):
	"""Resolve the adapter configured directly on a Generation Workflow."""
	adapter_key = str(getattr(workflow, "adapter_key", "") or "").strip()
	if not adapter_key:
		frappe.throw(
			frappe._("Generation Workflow {0} requires an adapter key.").format(workflow.name)
		)
	adapter = ADAPTERS.get(adapter_key)
	if not adapter:
		frappe.throw(
			frappe._("Unsupported generation adapter '{0}' for Generation Workflow {1}.").format(
				adapter_key, workflow.name
			)
		)
	return adapter()
