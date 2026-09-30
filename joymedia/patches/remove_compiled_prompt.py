import frappe
from frappe import _


def execute():
	if (
		frappe.db.table_exists("Compiled Prompt")
		and frappe.db.table_exists("Generation Job")
		and frappe.db.has_column("Generation Job", "compiled_prompt")
	):
		missing = frappe.db.sql(
			"""
			SELECT job.name
			FROM `tabGeneration Job` job
			WHERE
				job.compiled_prompt IS NOT NULL
				AND job.compiled_prompt != ''
				AND (
					job.prompt_text IS NULL
					OR job.prompt_text = ''
					OR job.prompt_hash IS NULL
					OR job.prompt_hash = ''
				)
			LIMIT 1
			""",
			as_dict=True,
		)
		if missing:
			frappe.throw(
				_(
					"Cannot remove Compiled Prompt because Generation Job {0} "
					"still lacks a migrated prompt snapshot."
				).format(missing[0].name)
			)

	if frappe.db.exists("DocType", "Compiled Prompt"):
		frappe.delete_doc("DocType", "Compiled Prompt", ignore_permissions=True, force=True)
