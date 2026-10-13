"""Deterministic import for the Shera-style advertising storyboard workbook.

The importer intentionally does not ask an LLM to recover rows from a spreadsheet.
It preserves the supplied Vietnamese or English source text and reports timing gaps for
the editor to resolve before a project can be approved for rendering.
"""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import load_workbook


SCENE_HEADERS = {"phân cảnh", "scene", "scenes"}
NONE_MARKERS = {"", "x", "n/a", "na", "none", "-"}
METADATA_LABELS = {
	"tên sản phẩm": "product_name",
	"product name": "product_name",
	"mục tiêu": "objective",
	"objective": "objective",
	"usp chính": "usp",
	"primary usp": "usp",
	"thời lượng": "duration",
	"duration": "duration",
	"định dạng": "format",
	"format": "format",
	"tone & mood": "tone_mood",
	"tone and mood": "tone_mood",
	"nhân vật": "characters",
	"characters": "characters",
	"tài nguyên": "asset_requirements",
	"assets": "asset_requirements",
}


def parse_storyboard_workbook(path: str | Path) -> dict:
	"""Parse every supported sheet without changing source copy or timing."""
	workbook = load_workbook(filename=path, data_only=True, read_only=True)
	demos = []
	for worksheet in workbook.worksheets:
		demo = _parse_sheet(worksheet)
		if demo["scenes"]:
			demos.append(demo)
	if not demos:
		raise ValueError("The workbook has no storyboard scene table.")
	return {"format": "joymedia-storyboard-v1", "demos": demos}


def _parse_sheet(sheet) -> dict:
	rows = list(sheet.iter_rows(values_only=True))
	header_index = next(
		(index for index, row in enumerate(rows) if _cell(row, 0).casefold() in SCENE_HEADERS),
		None,
	)
	if header_index is None:
		raise ValueError(f"Sheet '{sheet.title}' has no scene header.")
	metadata = _metadata(rows[:header_index])
	scenes = []
	for row in rows[header_index + 1 :]:
		name = _cell(row, 0)
		if not name:
			continue
		timing = _cell(row, 1)
		start, end = parse_time_range(timing)
		if start is None:
			# A note or accidental row beneath the table is not a storyboard beat.
			continue
		scenes.append(
			{
				"source_row": len(scenes) + header_index + 2,
				"beat_name": name,
				"source_timing": timing,
				"start_seconds": start,
				"end_seconds": end,
				"duration_seconds": end - start,
				"visual_camera": _cell(row, 2),
				"action": _cell(row, 3),
				"voice_over": _cell(row, 4),
				"audio_cues": _cell(row, 5),
				"on_screen_text": _meaningful_text(_cell(row, 6)),
				"illustration_reference": _meaningful_text(_cell(row, 7)),
				# A workbook does not imply visual continuity. Editors explicitly choose
				# Continue only after reviewing the planned composition.
				"continuity_mode": "New Scene",
			}
		)
	target_seconds = parse_duration_seconds(metadata.get("duration", ""))
	return {
		"name": sheet.title,
		"metadata": metadata,
		"scenes": scenes,
		"timing_warnings": timing_warnings(scenes, target_seconds),
	}


def _metadata(rows) -> dict:
	metadata = {}
	for row in rows:
		label = _cell(row, 0).casefold()
		key = METADATA_LABELS.get(label)
		if not key:
			continue
		value = _cell(row, 1)
		if not value:
			continue
		if key == "usp" and metadata.get(key):
			metadata[key] = f"{metadata[key]}\n{value}"
		else:
			metadata[key] = value
	return metadata


def parse_duration_seconds(value: str) -> float | None:
	match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:s|sec|seconds|giây)?", str(value or ""), re.I)
	return float(match.group(1).replace(",", ".")) if match else None


def parse_time_range(value: str) -> tuple[float | None, float | None]:
	parts = re.findall(r"(\d{1,2}):(\d{2})(?:[.,](\d+))?", str(value or ""))
	if len(parts) != 2:
		return None, None
	seconds = [int(minutes) * 60 + int(second) + float(f"0.{fraction}" if fraction else 0) for minutes, second, fraction in parts]
	return (seconds[0], seconds[1]) if seconds[1] > seconds[0] else (None, None)


def timing_warnings(scenes: list[dict], target_seconds: float | None) -> list[dict]:
	warnings = []
	previous_end = 0.0
	for scene in sorted(scenes, key=lambda item: item["start_seconds"]):
		if scene["start_seconds"] > previous_end:
			warnings.append({
				"type": "gap",
				"start_seconds": previous_end,
				"end_seconds": scene["start_seconds"],
				"message": f"No authored scene covers {previous_end:g}s–{scene['start_seconds']:g}s.",
			})
		elif scene["start_seconds"] < previous_end:
			warnings.append({
				"type": "overlap",
				"start_seconds": scene["start_seconds"],
				"end_seconds": previous_end,
				"message": f"Storyboard scenes overlap from {scene['start_seconds']:g}s–{previous_end:g}s.",
			})
		previous_end = max(previous_end, scene["end_seconds"])
	if target_seconds and previous_end < target_seconds:
		warnings.append({
			"type": "gap",
			"start_seconds": previous_end,
			"end_seconds": target_seconds,
			"message": f"No authored scene covers {previous_end:g}s–{target_seconds:g}s.",
		})
	return warnings


def _cell(row, index: int) -> str:
	return str(row[index] or "").strip() if len(row) > index else ""


def _meaningful_text(value: str) -> str:
	return "" if value.casefold().strip() in NONE_MARKERS else value
