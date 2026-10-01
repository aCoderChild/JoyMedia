import frappe


def execute():
	if (
		frappe.db.table_exists("Compiled Prompt")
		and frappe.db.table_exists("Generation Task")
		and frappe.db.has_column("Generation Task", "compiled_prompt")
	):
		frappe.db.sql(
			"""
			UPDATE `tabGeneration Task` job
			INNER JOIN `tabCompiled Prompt` prompt
				ON prompt.name = job.compiled_prompt
			SET
				job.prompt_text = prompt.prompt_text,
				job.prompt_hash = prompt.prompt_hash
			WHERE
				job.compiled_prompt IS NOT NULL
				AND job.compiled_prompt != ''
				AND (
					job.prompt_text IS NULL
					OR job.prompt_text = ''
					OR job.prompt_hash IS NULL
					OR job.prompt_hash = ''
				)
			"""
		)
