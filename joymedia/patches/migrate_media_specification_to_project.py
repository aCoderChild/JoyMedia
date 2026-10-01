import frappe


def execute():
	"""Copy the active generation relationship and settings onto Media Project.

	Media Specification remains available as a compatibility DocType. This patch only
	backfills the new project-owned fields and relationships; it does not delete data.
	"""
	if not frappe.db.table_exists("Media Project"):
		return

	if frappe.db.table_exists("Media Specification"):
		rows = frappe.db.sql(
			"""
			SELECT name, media_project, total_duration_seconds, delivery_preset,
			       delivery_width, delivery_height, continuity_mode,
			       global_instructions, workflow
			FROM `tabMedia Specification`
			WHERE media_project IS NOT NULL AND media_project != ''
			ORDER BY version_number DESC, creation DESC
			""",
			as_dict=True,
		)
		seen_projects = set()
		for row in rows:
			if row.media_project in seen_projects:
				continue
			seen_projects.add(row.media_project)
			frappe.db.set_value(
				"Media Project",
				row.media_project,
				{
					"total_duration_seconds": row.total_duration_seconds,
					"delivery_preset": row.delivery_preset,
					"delivery_width": row.delivery_width,
					"delivery_height": row.delivery_height,
					"generation_mode": row.continuity_mode or "Multi-shot",
					"global_instructions": row.global_instructions,
					"workflow": row.workflow,
				},
				update_modified=False,
			)

		if (
			frappe.db.table_exists("Shot")
			and frappe.db.has_column("Shot", "media_project")
			and frappe.db.has_column("Shot", "media_specification")
		):
			frappe.db.sql(
				"""
				UPDATE `tabShot` shot
				INNER JOIN `tabMedia Specification` spec
				  ON spec.name = shot.media_specification
				SET shot.media_project = spec.media_project
				WHERE (shot.media_project IS NULL OR shot.media_project = '')
				"""
			)

		if (
			frappe.db.table_exists("Generation Run")
			and frappe.db.has_column("Generation Run", "media_project")
			and frappe.db.has_column("Generation Run", "media_specification")
		):
			frappe.db.sql(
				"""
				UPDATE `tabGeneration Run` run
				INNER JOIN `tabMedia Specification` spec
				  ON spec.name = run.media_specification
				SET run.media_project = spec.media_project,
				    run.workflow = COALESCE(run.workflow, spec.workflow)
				WHERE (run.media_project IS NULL OR run.media_project = '')
				"""
			)

	frappe.clear_cache()
