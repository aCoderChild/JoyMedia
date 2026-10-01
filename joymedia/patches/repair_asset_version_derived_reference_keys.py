import re

import frappe


def execute():
	"""Replace keys generated from Asset Version IDs by logical asset names."""
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
		used = used_by_parent.setdefault(row.parent, set())
		if not str(row.reference_key or "").startswith("astv_"):
			used.add(row.reference_key)
			continue
		asset_name = frappe.db.get_value("Asset Version", row.asset_version, "media_asset")
		logical_name = frappe.db.get_value("Media Asset", asset_name, "asset_name") if asset_name else None
		base = re.sub(r"[^a-z0-9]+", "_", str(row.label or logical_name or "reference").lower()).strip("_")
		base = (base or "reference")[:100]
		key = base
		counter = 2
		while key in used:
			suffix = f"_{counter}"
			key = f"{base[:100 - len(suffix)]}{suffix}"
			counter += 1
		frappe.db.set_value("Project Reference", row.name, "reference_key", key, update_modified=False)
		used.add(key)
