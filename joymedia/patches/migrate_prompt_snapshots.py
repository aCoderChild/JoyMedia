import frappe


def execute():
	frappe.db.sql(
		"""
		UPDATE `tabGeneration Job` job
		INNER JOIN `tabCompiled Prompt` prompt
			ON prompt.name = job.compiled_prompt
		SET job.prompt_text = prompt.prompt_text,
			job.prompt_hash = prompt.prompt_hash
		WHERE (job.prompt_text IS NULL OR job.prompt_text = '')
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabWorkflow Binding`
		SET value_source = 'Generation Prompt'
		WHERE value_source = 'Compiled Prompt'
		"""
	)
