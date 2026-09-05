import frappe


COMPOSITE_UNIQUES = (
	("Asset Version", ("media_asset", "version_number"), "uniq_asset_version_media_asset_version"),
	("Workflow Version", ("workflow_profile", "version_number"), "uniq_workflow_version_profile_version"),
	("Prompt Template Version", ("prompt_template", "version_number"), "uniq_prompt_template_version_template_version"),
	("Media Specification", ("media_project", "version_number"), "uniq_media_spec_project_version"),
	("Shot Specification", ("media_specification", "shot_number"), "uniq_shot_spec_media_spec_number"),
	("Generation Attempt", ("generation_job", "attempt_number"), "uniq_generation_attempt_job_number"),
)


def execute():
	for doctype, fields, constraint_name in COMPOSITE_UNIQUES:
		frappe.db.add_unique(doctype, fields, constraint_name)
