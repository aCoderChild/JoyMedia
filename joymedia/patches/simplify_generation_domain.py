import frappe


DEFAULT_ADAPTER_KEY = "minimax_h3"


def execute():
	_migrate_workflow_adapter_key()
	_normalize_artifact_roles()
	_remove_dead_doctypes()


def _migrate_workflow_adapter_key():
	if not frappe.db.table_exists("Generation Workflow"):
		return
	if not frappe.db.has_column("Generation Workflow", "adapter_key"):
		return

	profile_adapter_by_name = {}
	if (
		frappe.db.table_exists("AI Model Profile")
		and frappe.db.has_column("AI Model Profile", "adapter_key")
	):
		profile_adapter_by_name = {
			row.name: row.adapter_key
			for row in frappe.get_all("AI Model Profile", fields=["name", "adapter_key"])
			if row.adapter_key
		}

	has_old_profile_link = frappe.db.has_column("Generation Workflow", "ai_model_profile")
	fields = ["name", "adapter_key"]
	if has_old_profile_link:
		fields.append("ai_model_profile")

	for workflow in frappe.get_all("Generation Workflow", fields=fields):
		if str(workflow.adapter_key or "").strip():
			continue
		adapter_key = DEFAULT_ADAPTER_KEY
		if has_old_profile_link and workflow.ai_model_profile:
			adapter_key = profile_adapter_by_name.get(workflow.ai_model_profile) or DEFAULT_ADAPTER_KEY
		frappe.db.set_value(
			"Generation Workflow",
			workflow.name,
			"adapter_key",
			adapter_key,
			update_modified=False,
		)


def _normalize_artifact_roles():
	if not frappe.db.table_exists("Generation Artifact"):
		return
	if not frappe.db.has_column("Generation Artifact", "artifact_role"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabGeneration Artifact`
		SET artifact_role = 'Primary Video'
		WHERE artifact_role = 'Final Video'
		"""
	)


def _remove_dead_doctypes():
	# These objects no longer participate in the generation path. Generation
	# Workflow owns adapter selection directly and Qwen generates prompts from
	# Media Project.video_idea, so prompt-template/model-profile registries add
	# identity and lifecycle without a real product responsibility.
	for doctype_name in ("Prompt Template Version", "Prompt Template", "AI Model Profile"):
		if frappe.db.exists("DocType", doctype_name):
			frappe.delete_doc(
				"DocType",
				doctype_name,
				ignore_permissions=True,
				force=True,
			)
