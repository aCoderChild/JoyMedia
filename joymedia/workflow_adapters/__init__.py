from .minimax_h3 import MiniMaxH3WorkflowAdapter


def get_workflow_adapter(workflow):
	"""Return the adapter for a workflow without guessing unsupported model families."""
	return MiniMaxH3WorkflowAdapter()
