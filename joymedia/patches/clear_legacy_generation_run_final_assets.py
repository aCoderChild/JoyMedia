import frappe


def execute():
	"""Remove obsolete run-level project exports after timeline export separation.

	Generation Run now owns only generation execution state. Explicit editor
	exports live on Media Project.current_output_asset_version, so historical
	run.final_asset_version values must not be able to masquerade as current
	project deliveries through compatibility read paths.
	"""
	if not frappe.db.has_column("Generation Run", "final_asset_version"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabGeneration Run`
		SET final_asset_version = NULL
		WHERE final_asset_version IS NOT NULL
		"""
	)
