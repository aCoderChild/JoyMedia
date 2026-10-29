"""Resolve generated asset variants against their selected project sources."""

import frappe

from joymedia.services.scene.references import identity_key, value


def original_reference(asset_version):
	"""Resolve the immutable original, never a progressively edited view as identity authority."""
	from joymedia.services.consistency.tracking import file_hash

	seen = set()
	for _ in range(16):
		if asset_version in seen:
			raise ValueError("Reference identity lineage contains a cycle.")
		seen.add(asset_version)
		version = frappe.db.get_value(
			"Asset Version",
			asset_version,
			["name", "file", "content_hash", "analysis_json", "derived_from"],
			as_dict=True,
		)
		if not version:
			raise ValueError("The original reference lineage is unavailable.")
		analysis = frappe.parse_json(version.analysis_json or "{}")
		if not isinstance(analysis, dict):
			raise ValueError("Reference identity metadata must be an object.")
		parent = (
			analysis.get("source_asset_version")
			or (analysis.get("subject_cutout") or {}).get("source_asset_version")
			or version.derived_from
		)
		if parent:
			asset_version = parent
			continue
		if not version.file or not version.content_hash:
			raise ValueError("The original identity reference has no immutable image evidence.")
		path = frappe.get_doc("File", {"file_url": version.file}).get_full_path()
		if file_hash(path) != version.content_hash:
			raise ValueError("The original identity reference bytes changed.")
		return {"asset_version": version.name, "file": version.file, "content_hash": version.content_hash}
	raise ValueError("Reference identity lineage exceeds the supported depth.")


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
