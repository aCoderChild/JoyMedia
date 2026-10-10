"""Immutable, linear pipeline lookup for Generation Runs.

Pipelines deliberately reference versioned Generation Workflow records.  A run stores
the selected pipeline name, so later workflow registrations cannot change an existing
execution plan.
"""

import frappe
from frappe import _


def pipeline_for_final_workflow(workflow_name):
	"""Return the newest production-default pipeline, preferring candidates only as fallback.

	Candidate pipelines remain explicitly selectable in project settings but must
	not silently replace an established default merely because they were registered
	later.
	"""
	rows = frappe.get_all(
		"Generation Pipeline", fields=["name", "pipeline_key"],
		order_by="version_number desc, modified desc",
	)
	rows.sort(key=lambda row: "candidate" in str(row.pipeline_key or "").lower())
	for row in rows:
		pipeline = frappe.get_doc("Generation Pipeline", row.name)
		if pipeline.steps and pipeline.steps[-1].workflow == workflow_name:
			return pipeline
	return None


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
