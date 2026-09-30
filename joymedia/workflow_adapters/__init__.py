import frappe

from .minimax_h3 import MiniMaxH3WorkflowAdapter


ADAPTERS = {
	"minimax_h3": MiniMaxH3WorkflowAdapter,
}


def get_workflow_adapter(workflow):
	"""Resolve a workflow's explicitly configured model adapter."""
	profile_name = getattr(workflow, "ai_model_profile", None)
	if not profile_name:
		frappe.throw(frappe._("Generation Workflow {0} requires an AI Model Profile.").format(workflow.name))
	adapter_key = frappe.db.get_value("AI Model Profile", profile_name, "adapter_key")
	adapter = ADAPTERS.get(adapter_key)
	if not adapter:
		frappe.throw(
			frappe._("Unsupported AI model adapter '{0}' for AI Model Profile {1}.").format(
				adapter_key or "(empty)", profile_name
			)
		)
	return adapter()
