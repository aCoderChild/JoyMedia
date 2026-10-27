"""A silent, progressive rough cut for an automatic creative batch.

The final timeline deliberately waits for all source clips, music and narration.
That is the right rule for a deliverable, but it is a poor way to let a marketer
understand the film while ComfyUI is still rendering it.  This module makes a
separate, explicitly provisional cut: completed scenes play as video and scenes
still waiting for video hold on their approved first frame.  It never changes the
editable timeline or the final export.
"""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe.utils.file_manager import save_file

from joymedia.services.editing.composer import _get_artifact_path, _get_asset_version_path
from joymedia.services.project.render_queue import enqueue_render


def queue_progressive_preview(batch_name: str, variant_index: int, project_name: str):
	"""Queue a current silent rough cut without making generation wait for it."""
	signature = _source_signature(project_name)
	enqueue_render(
		"joymedia.services.editing.rough_preview.render_progressive_preview",
		f"joymedia:rough-preview:{batch_name}:{variant_index}:{signature[:12]}",
		timeout=900,
		batch_name=batch_name,
		variant_index=int(variant_index),
		project_name=project_name,
		expected_signature=signature,
	)


def _source_signature(project_name: str) -> str:
	shots = frappe.get_all(
		"Shot",
		filters={"media_project": project_name, "is_removed": 0},
		fields=["name", "duration_seconds", "selected_output_asset_version", "keyframe_artifact"],
		order_by="shot_number asc, name asc",
	)
	identity = [
		(
			s.name,
			float(s.duration_seconds or 0),
			s.selected_output_asset_version,
			s.keyframe_artifact,
			frappe.db.get_value(
				"Shot Reference", {"parent": s.name, "reference_role": "first_frame"}, "asset_version"
			),
		)
		for s in shots
	]
	return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def _profile(project):
	return {
		"width": int(project.delivery_width or 720),
		"height": int(project.delivery_height or 1280),
		"fps": int(project.get("delivery_fps") or 24),
	}


def _first_frame_path(shot):
	"""The approved still is a visual placeholder, never an invented asset."""
	control = frappe.db.get_value(
		"Shot Reference", {"parent": shot.name, "reference_role": "first_frame"}, "asset_version"
	)
	if control:
		return _get_asset_version_path(control)
	if shot.keyframe_artifact:
		return _get_artifact_path(frappe.get_doc("Generation Artifact", shot.keyframe_artifact))
	return None


def _run(command):
	subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def _segment(path: Path, destination: Path, seconds: float, profile: dict, *, image: bool):
	seconds = max(0.25, float(seconds or 0.25))
	filter_graph = (
		f"fps={profile['fps']},scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=decrease,"
		f"pad={profile['width']}:{profile['height']}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p"
	)
	command = ["ffmpeg", "-v", "error", "-y"]
	if image:
		command += ["-loop", "1", "-i", str(path)]
	else:
		# A generated clip can be shorter than its authored scene.  Looping it is
		# acceptable only in this draft and preserves the storyboard timing.
		command += ["-stream_loop", "-1", "-i", str(path)]
	command += [
		"-t",
		f"{seconds:.3f}",
		"-an",
		"-vf",
		filter_graph,
		"-c:v",
		"libx264",
		"-preset",
		"veryfast",
		"-crf",
		"24",
		"-movflags",
		"+faststart",
		str(destination),
	]
	_run(command)


def render_progressive_preview(
	batch_name: str, variant_index: int, project_name: str, expected_signature: str | None = None
):
	"""Render and attach the latest silent rough cut for one variant."""
	batch = frappe.get_doc("Creative Batch", batch_name)
	variants = frappe.parse_json(batch.variants_json or "[]")
	if batch.status == "Cancelled" or not 0 <= int(variant_index) < len(variants):
		return
	variant = variants[int(variant_index)]
	if variant.get("project") != project_name:
		return
	project = frappe.get_doc("Media Project", project_name)
	profile = _profile(project)
	shots = frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		fields=["name", "duration_seconds", "selected_output_asset_version", "keyframe_artifact"],
		order_by="shot_number asc, name asc",
	)
	if not shots:
		return

	with tempfile.TemporaryDirectory(prefix=f"joymedia-rough-{project.name}-") as directory:
		directory = Path(directory)
		segments = []
		completed = 0
		included_shots = []
		for position, shot in enumerate(shots, start=1):
			output = directory / f"{position:03d}.mp4"
			if shot.selected_output_asset_version:
				path, image = _get_asset_version_path(shot.selected_output_asset_version), False
				completed += 1
				included_shots.append(shot.name)
			else:
				path, image = _first_frame_path(shot), True
			if not path:
				continue
			_segment(path, output, shot.duration_seconds, profile, image=image)
			segments.append(output)
		if not segments:
			return
		listing = directory / "segments.txt"
		listing.write_text(
			"\n".join(f"file '{str(path).replace("'", "'\\\\''")}'" for path in segments) + "\n"
		)
		output = directory / f"{project.name}-rough-preview.mp4"
		_run(
			[
				"ffmpeg",
				"-v",
				"error",
				"-y",
				"-f",
				"concat",
				"-safe",
				"0",
				"-i",
				str(listing),
				"-c",
				"copy",
				"-movflags",
				"+faststart",
				str(output),
			]
		)
		if expected_signature and _source_signature(project_name) != expected_signature:
			queue_progressive_preview(batch_name, variant_index, project_name)
			return
		file = save_file(
			f"{project.name}-rough-preview.mp4",
			output.read_bytes(),
			"Creative Batch",
			batch.name,
			is_private=1,
		)

	# Re-read after rendering: planning and generation may have written a newer
	# variant meanwhile.  The preview is allowed to lag, never to replace state.
	from joymedia.services.generation.creative_batch import _write

	latest = frappe.get_doc("Creative Batch", batch_name)
	variants = frappe.parse_json(latest.variants_json or "[]")
	if latest.status == "Cancelled" or not 0 <= int(variant_index) < len(variants):
		return
	if variants[int(variant_index)].get("project") != project_name:
		return
	if expected_signature and _source_signature(project_name) != expected_signature:
		queue_progressive_preview(batch_name, variant_index, project_name)
		return
	variants[int(variant_index)]["rough_preview"] = {
		"file": file.file_url,
		"completed_scenes": completed,
		"included_shots": included_shots,
		"total_scenes": len(shots),
		"sound": "pending",
		"source_signature": expected_signature or _source_signature(project_name),
	}
	_write(batch_name, variants, changed_index=int(variant_index))
