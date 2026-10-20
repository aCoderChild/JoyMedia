"""Who may read or edit a project's timeline."""


def _require_project_read(project):
	if hasattr(project, "_require_read_access"):
		project._require_read_access()
	else:
		project.check_permission("read")


def _require_project_write(project):
	if hasattr(project, "_require_write_access"):
		project._require_write_access()
	else:
		project.check_permission("write")


def _require_asset_version_access(project, version):
	"""Only project-owned outputs or explicitly selected library versions belong here."""
	import frappe

	asset = frappe.get_doc("Asset Version", version)
	parent = frappe.get_doc("Media Asset", asset.media_asset)
	if parent.media_project == project.name:
		return
	if parent.media_project or version not in {row.asset_version for row in project.selected_media or []}:
		frappe.throw("Asset Version does not belong to this project.", frappe.PermissionError)
