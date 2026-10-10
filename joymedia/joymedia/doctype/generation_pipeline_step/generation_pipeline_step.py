import frappe
from frappe import _
from frappe.model.document import Document


class GenerationPipelineStep(Document):
	def validate(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		immutable = ("step_key", "workflow", "prompt_source", "depends_on_step", "consumes_artifact_role", "produces_artifact_role")
		changed = [fieldname for fieldname in immutable if self.get(fieldname) != previous.get(fieldname)]
		if changed:
			frappe.throw(_("Generation Pipeline Steps are immutable after creation: {0}.").format(", ".join(changed)))
