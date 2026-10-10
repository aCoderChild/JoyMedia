import frappe

from .comfyui_generic import GenericComfyUIAdapter


ADAPTERS = {
	"comfyui_generic": GenericComfyUIAdapter,
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
			frappe._(
				"Generation Workflow {0} uses retired adapter '{1}'. "
				"Create a new immutable revision with adapter_key 'comfyui_generic' and an Execution Specification."
			).format(
				workflow.name, adapter_key
			)
		)
	instance = adapter()
	instance.workflow_version = workflow
	try:
		instance.execution_spec = frappe.parse_json(getattr(workflow, "execution_spec", None) or "{}")
	except (TypeError, ValueError):
		frappe.throw(frappe._("Generation Workflow {0} has invalid Execution Specification JSON.").format(workflow.name))
	if not isinstance(instance.execution_spec, dict):
		frappe.throw(frappe._("Generation Workflow {0} Execution Specification must be a JSON object.").format(workflow.name))
	return instance
