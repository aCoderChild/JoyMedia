"""Carry unresolved cut feedback forward when the edit reuses affected footage."""

import json
import math

import frappe


def affected_sources(manifest, feedback):
	"""Map inclusive review frames to immutable, half-open rendered segments.

	None means unavailable evidence, not an empty set of affected footage.
	At a dissolve both contributing sources must be reviewed.
	Video-wide findings may concern audio, captions or the overall edit and need
	explicit triage; replacing visual takes alone cannot establish a resolution.
	"""
	if feedback.get("scope") == "Video":
		return None
	try:
		manifest = json.loads(manifest) if isinstance(manifest, str) else manifest
		segments = manifest["render_timeline"]["segments"]
		if not isinstance(segments, list) or not segments:
			return None
		fps = float(feedback["fps"])
		first, last = float(feedback["start_frame"]), float(feedback["end_frame"])
		if not all(math.isfinite(v) for v in (fps, first, last)) or fps <= 0 or first < 0 or last < first:
			return None
		start, end = first / fps, (last + 1) / fps
		sources = set()
		for row in segments:
			a, b = float(row["start_seconds"]), float(row["end_seconds"])
			source = row["source_asset_version"]
			if (
				not all(math.isfinite(v) for v in (a, b))
				or a < 0
				or b <= a
				or not isinstance(source, str)
				or not source
			):
				return None
			if a < end and b > start:
				sources.add(source)
		return sources or None  # gaps/unknown overlays need administrator triage
	except (KeyError, ValueError, TypeError, OverflowError):
		return None


def unresolved_cut_feedback(project_name, clips, *, lock=False):
	"""Exact source identity survives branch copies and deterministic derivatives.

	A new output filename, re-export, or renamed edit cannot resolve a finding.
	Replacing all affected source takes or explicitly triaging the record can.
	"""
	sources = {
		row.get("source_asset_version")
		for row in clips
		if row.get("enabled", 1) and (row.get("track_type") or "Video") == "Video"
	} - {None, ""}
	if not sources:
		return []
	root = frappe.db.get_value("Media Project", project_name, "version_of") or project_name
	rows = frappe.db.sql(
		"""select f.name, f.scope, f.start_frame, f.end_frame, f.fps, v.edit_manifest_json
		from `tabVideo Review Feedback` f inner join `tabAsset Version` v on v.name=f.asset_version
		where f.media_project=%s and (f.shot is null or f.shot='')
		and f.status in ('Open', 'Investigating')"""
		+ (" for update" if lock else ""),
		root,
		as_dict=True,
	)
	if not rows:
		return []
	# Copies preserve derived_from. Do not let copying an old take bypass review.
	for initial in list(sources):
		seen, current = set(), initial
		for _ in range(32):
			if not current:
				break
			if current in seen:
				raise ValueError("Release blocked: cyclic source footage lineage needs review.")
			seen.add(current)
			sources.add(current)
			current = frappe.db.get_value("Asset Version", current, "derived_from")
		else:
			raise ValueError("Release blocked: source footage lineage exceeds the review limit.")
	return [
		row.name
		for row in rows
		if (affected := affected_sources(row.edit_manifest_json, row)) is None
		or sources.intersection(affected)
	]
