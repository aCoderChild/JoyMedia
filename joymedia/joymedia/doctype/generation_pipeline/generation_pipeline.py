import frappe
from frappe import _
from frappe.model.document import Document


class GenerationPipeline(Document):
	IMMUTABLE_FIELDS = (
		"pipeline_key", "version_number", "output_media_type", "steps",
	)

	def validate(self):
		if self.is_new():
			latest = frappe.get_all(
				"Generation Pipeline",
				filters={"pipeline_key": self.pipeline_key},
				fields=["version_number"],
				order_by="version_number desc",
				limit_page_length=1,
			)
			self.version_number = int(latest[0].version_number or 0) + 1 if latest else 1
		if not self.steps:
			frappe.throw(_("Generation Pipeline requires at least one step."))
		seen = set()
		for step in self.steps:
			if not step.step_key or step.step_key in seen:
				frappe.throw(_("Every Pipeline Step needs a unique Step Key."))
			seen.add(step.step_key)
			if not frappe.db.exists("Generation Workflow", step.workflow):
				frappe.throw(_("Pipeline Step {0} references an unavailable Generation Workflow.").format(step.step_key))
			workflow = frappe.get_doc("Generation Workflow", step.workflow)
			if step.produces_artifact_role != workflow.primary_artifact_role:
				frappe.throw(_("Pipeline Step {0} must produce the workflow's primary artifact role ({1}).").format(step.step_key, workflow.primary_artifact_role))
		self.output_media_type = frappe.get_doc("Generation Workflow", self.steps[-1].workflow).output_media_type
		self._validate_immutability()

	def _validate_immutability(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		changed = [
			fieldname for fieldname in self.IMMUTABLE_FIELDS
			if self.get(fieldname) != previous.get(fieldname)
		]
		if changed:
			frappe.throw(
				_("Generation Pipeline is immutable after creation. Create a new version instead: {0}.").format(
					", ".join(changed)
				)
			)
