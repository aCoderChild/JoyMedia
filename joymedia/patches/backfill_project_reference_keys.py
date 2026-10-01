import re

import frappe


def execute():
	"""Backfill stable, project-local keys for existing Project Reference rows."""
	if not frappe.db.table_exists("Project Reference") or not frappe.db.has_column(
		"Project Reference", "reference_key"
	):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, parent, reference_key, label, asset_version
		FROM `tabProject Reference`
		ORDER BY parent, idx, name
		""",
		as_dict=True,
	)
	used_by_parent = {}
	for row in rows:
		parent_used = used_by_parent.setdefault(row.parent, set())
		key = str(row.reference_key or "").strip().lower()
		if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", key) or key in parent_used:
			asset_name = frappe.db.get_value("Asset Version", row.asset_version, "media_asset")
			base = row.label or (
				frappe.db.get_value("Media Asset", asset_name, "asset_name") if asset_name else ""
			) or "reference"
			base = re.sub(r"[^a-z0-9]+", "_", str(base).lower()).strip("_") or "reference"
			key = base[:100]
			counter = 2
			while key in parent_used:
				suffix = f"_{counter}"
				key = f"{base[:100 - len(suffix)]}{suffix}"
				counter += 1
			frappe.db.set_value("Project Reference", row.name, "reference_key", key, update_modified=False)
		parent_used.add(key)
