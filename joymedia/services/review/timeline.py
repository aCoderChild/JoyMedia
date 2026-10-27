"""Sanitized timing for an immutable review version, never the mutable editor."""

import json
import math

import frappe


def timeline_from_manifest(manifest, fps, total_frames):
	try:
		manifest = json.loads(manifest) if isinstance(manifest, str) else manifest
		render = manifest.get("render_timeline") if isinstance(manifest, dict) else None
		if not isinstance(render, dict) or not isinstance(render.get("segments"), list):
			return []
		result = []
		for index, row in enumerate(render["segments"][:300]):
			if not isinstance(row, dict):
				return []
			start, end = float(row["start_seconds"]), float(row["end_seconds"])
			if not all(math.isfinite(v) for v in (start, end)) or start < 0 or end <= start:
				return []
			first, last = round(start * fps), min(total_frames, round(end * fps))
			if first >= last:
				continue
			result.append(
				{
					"id": str(index),
					"title": str(row.get("title") or f"Scene {index + 1}")[:180],
					"start_frame": first,
					"end_frame": last,
					"direction": str(row.get("direction") or "")[:4000],
				}
			)
		return result
	except (ValueError, TypeError, KeyError, OverflowError):
		return []


def _viewer_scene_names(project_name, segments):
	"""Name each scene as the viewer reads it: the AI script's localized scene title, when it has one."""
	for name in frappe.get_all(
		"Creative Batch", filters={"variants_json": ["like", f"%{project_name}%"]}, pluck="name", limit=5
	):
		for variant in frappe.parse_json(
			frappe.db.get_value("Creative Batch", name, "variants_json") or "[]"
		):
			scenes = (variant.get("script") or {}).get("scenes") or []
			if variant.get("project") == project_name and len(scenes) == len(segments):
				for segment, scene in zip(segments, scenes, strict=True):
					segment["title"] = str(scene.get("display_name") or segment["title"])[:180]
				return


@frappe.whitelist()
def get_review_timeline(project_name, asset_version):
	from joymedia.services.review.feedback import target

	_root, _asset, version, shot, fps, total = target(project_name, asset_version)
	if shot:
		segments = [{"id": "0", "title": "Scene", "start_frame": 0, "end_frame": total, "direction": ""}]
		source = "scene"
	else:
		segments = timeline_from_manifest(version.edit_manifest_json, fps, total)
		source = "export" if segments else "unavailable"
		_viewer_scene_names(project_name, segments)
	from joymedia.services.partners import is_reviewer

	reviewer = is_reviewer()
	if reviewer:
		for segment in segments:
			segment.pop("direction", None)
	filters = {"asset_version": version.name}
	if reviewer:
		filters["owner"] = frappe.session.user
	markers = frappe.get_all(
		"Video Review Feedback",
		filters=filters,
		fields=["name", "scope", "start_frame", "end_frame", "feedback", "status"],
		order_by="creation asc, name asc",
		limit_page_length=501,
	)
	return {
		"markers": markers[:500],
		"markers_has_more": len(markers) > 500,
		"asset_version": version.name,
		"fps": fps,
		"total_frames": total,
		"segments": segments,
		"timing_source": source,
	}


def rendered_segments(clips, lengths, transitions, positioned, fps, scenes):
	by_shot = {row["name"]: row for row in scenes}
	cursor, result = 0, []
	for index, (clip, length) in enumerate(zip(clips, lengths, strict=False)):
		start = int(clip.get("timeline_start_frame") or 0) if positioned else cursor
		scene = by_shot.get(clip.get("shot"), {})
		result.append(
			{
				"start_seconds": start / fps,
				"end_seconds": (start + length) / fps,
				"title": scene.get("shot_name") or f"Scene {index + 1}",
				"direction": scene.get("generation_prompt") or "",
				"source_asset_version": clip.get("source_asset_version"),
			}
		)
		cursor = start + length - (transitions[index] if index < len(transitions) else 0)
	return result
