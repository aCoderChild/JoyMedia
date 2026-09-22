from .base import GenericWorkflowAdapter
from .minimax_h3 import MiniMaxH3WorkflowAdapter


def get_workflow_adapter(workflow):
	"""Return the adapter for a workflow without guessing unsupported model families."""
	if "h3" in ((workflow.workflow_code or "").lower()):
		return MiniMaxH3WorkflowAdapter()
	return GenericWorkflowAdapter()
