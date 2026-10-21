"""Immutable, linear pipeline lookup for Generation Runs.

Pipelines deliberately reference versioned Generation Workflow records.  A run stores
the selected pipeline name, so later workflow registrations cannot change an existing
execution plan.
"""

from contextlib import contextmanager

import frappe
from frappe import _


@contextmanager
def pinned_execution(project_name, pipeline_name):
	"""Scope a trusted server-side execution snapshot to a native operation.

	This is not an RPC or a client model selector. Durable orchestration supplies
	its immutable backend-selected pipeline; native runs freeze their own steps.
	"""
	previous = frappe.flags.get("joymedia_execution_pipelines")
	frappe.flags.joymedia_execution_pipelines = {**(previous or {}), project_name: pipeline_name}
	try:
		yield
	finally:
		frappe.flags.joymedia_execution_pipelines = previous


def get_pinned_generation_pipeline(project_name):
	"""An operator's explicit per-project deployment pin; never a client model choice."""
	import json

	value = frappe.conf.get("joymedia_project_generation_pipelines")
	if value is None:
		value = frappe.defaults.get_global_default("joymedia_project_generation_pipelines") or {}
	if isinstance(value, str):
		value = json.loads(value)
	if not isinstance(value, dict):
		raise ValueError("Project generation pipeline pins must be a mapping.")
	name = (frappe.flags.get("joymedia_execution_pipelines") or {}).get(project_name) or value.get(
		project_name
	)
	if not name:
		return None
	if not isinstance(name, str) or not frappe.db.exists("Generation Pipeline", name):
		raise ValueError("The project's pinned Generation Pipeline is unavailable.")
	pipeline = frappe.get_doc("Generation Pipeline", name)
	get_pipeline_steps(name)
	return pipeline


def get_active_generation_pipeline():
	"""Return the one pipeline deliberately promoted by the site administrator.

	A workflow/pipeline version is immutable, but its creation is not a promotion.
	Using the latest row here would let an unvalidated candidate alter customer
	renders. Configure ``joymedia_active_generation_pipeline`` in site_config or
	as a global default after a smoke test has passed.
	"""
	name = frappe.conf.get("joymedia_active_generation_pipeline") or frappe.defaults.get_global_default(
		"joymedia_active_generation_pipeline"
	)
	if not name:
		frappe.throw(
			_("No active Generation Pipeline is configured. Set joymedia_active_generation_pipeline.")
		)
	if not frappe.db.exists("Generation Pipeline", name):
		frappe.throw(_("Configured active Generation Pipeline {0} does not exist.").format(name))
	pipeline = frappe.get_doc("Generation Pipeline", name)
	get_pipeline_steps(pipeline.name)
	return pipeline


def pipeline_for_final_workflow(workflow_name):
	"""Return the configured pipeline only when its immutable final step matches."""
	pipeline = get_active_generation_pipeline()
	return pipeline if pipeline.steps[-1].workflow == workflow_name else None


def get_pipeline_steps(pipeline_name):
	if not pipeline_name:
		return []
	pipeline = frappe.get_doc("Generation Pipeline", pipeline_name)
	steps = list(pipeline.steps or [])
	if not steps:
		frappe.throw(_("Generation Pipeline {0} has no steps.").format(pipeline.name))
	step_keys = {step.step_key for step in steps}
	for index, step in enumerate(steps):
		if index == 0:
			if step.depends_on_step:
				frappe.throw(_("The first Pipeline Step cannot depend on another step."))
		elif step.depends_on_step != steps[index - 1].step_key:
			frappe.throw(
				_("Generation Pipeline {0} must be a linear ordered pipeline.").format(pipeline.name)
			)
		if step.depends_on_step and step.depends_on_step not in step_keys:
			frappe.throw(_("Pipeline Step {0} has an unknown dependency.").format(step.step_key))
	return steps
