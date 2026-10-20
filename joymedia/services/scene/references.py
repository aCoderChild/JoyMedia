"""Canonical identities for project reference variants.

A project can contain several pictures of the same subject: for example a
front, side and three-quarter view of one subject.  They are *variants* of one
identity, not separate physical subjects.  This module keeps that distinction out
of planners and workflow adapters, which only need a stable identity key and
the concrete assets to condition a render.
"""

from __future__ import annotations

from collections import OrderedDict


def value(row, fieldname, default=""):
	"""Read a field from either a Frappe child document or a dict."""
	if hasattr(row, "get"):
		return row.get(fieldname, default)
	return getattr(row, fieldname, default)


def identity_key(row):
	"""Return a reference's canonical identity, falling back compatibly."""
	return str(value(row, "identity_key") or value(row, "reference_key") or "").strip()


def canonical_reference_rows(rows):
	"""Return the first (canonical) row for each identity in project order."""
	canonical = OrderedDict()
	for row in rows or []:
		key = identity_key(row)
		if key and key not in canonical:
			canonical[key] = row
	return list(canonical.values())


def expand_reference_keys(rows, reference_keys, *, view_keys=None):
	"""Expand selected reference keys to all approved variants of each identity.

	The caller validates unknown keys.  Expansion deliberately preserves project
	order inside an identity, so an immutable task snapshot is reproducible.
	"""
	by_reference_key = {str(value(row, "reference_key") or ""): row for row in rows or []}
	selected_identities = {
		identity_key(by_reference_key[key]) for key in reference_keys if key in by_reference_key
	}
	view_keys = set(view_keys or [])
	for key in view_keys:
		if key not in by_reference_key or identity_key(by_reference_key[key]) not in selected_identities:
			raise ValueError("A selected view must belong to a declared scene identity.")
	constrained = {identity_key(by_reference_key[key]) for key in view_keys}
	expanded, seen_assets = [], set()
	for reference_key in reference_keys or []:
		row = by_reference_key.get(str(reference_key or ""))
		if not row:
			continue
		selected_identity = identity_key(row)
		for candidate in rows or []:
			if identity_key(candidate) != selected_identity:
				continue
			if selected_identity in constrained and value(candidate, "reference_key") not in view_keys:
				continue
			asset_version = str(value(candidate, "asset_version") or "")
			if not asset_version or asset_version in seen_assets:
				continue
			expanded.append(candidate)
			seen_assets.add(asset_version)
	return expanded


def named_reference_views(rows, names):
	"""Resolve exact workbook view names without inventing poses or new identities."""
	import unicodedata

	def normalize(text):
		return " ".join(unicodedata.normalize("NFC", str(text or "")).casefold().split())

	wanted = {normalize(name) for name in names if name}
	return [
		value(row, "reference_key")
		for row in rows or []
		if value(row, "reference_key")
		and wanted.intersection({
			normalize(str(value(row, "label")).split(" (", 1)[0]), normalize(value(row, "reference_key"))
		})
	]
