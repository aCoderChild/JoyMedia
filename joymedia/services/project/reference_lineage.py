"""Resolve generated asset variants against their selected project sources."""

import frappe

from joymedia.services.scene.references import identity_key, value


def lineage_identity(project, row):
	"""Follow recorded asset lineage within the same reference role."""
	selected = {value(item, "asset_version"): item for item in value(project, "selected_media", []) or []}
	role = str(value(row, "reference_role") or "").casefold()
	version = value(row, "asset_version")
	seen = set()
	while version and version not in seen:
		seen.add(version)
		try:
			analysis = (
				frappe.parse_json(frappe.db.get_value("Asset Version", version, "analysis_json") or "{}")
				or {}
			)
		except Exception:
			break
		parent = analysis.get("source_asset_version") or (analysis.get("subject_cutout") or {}).get(
			"source_asset_version"
		)
		if not parent or parent == version:
			break
		candidate = selected.get(parent)
		if not candidate or str(value(candidate, "reference_role") or "").casefold() != role:
			break
		row, version = candidate, parent
	return identity_key(row)
