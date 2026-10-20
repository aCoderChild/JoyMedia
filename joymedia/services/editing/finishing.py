"""Studio finishing: Real-ESRGAN x2 upscaling and RIFE interpolation to 60 fps.

The film is rendered at half the target size, cut into one-second chunks and
finished on ComfyUI chunk by chunk, so GPU memory stays bounded. Each chunk
carries the next chunk's first frame, so RIFE also interpolates across chunk
boundaries; ComfyUI drops that duplicate frame again, so the finished chunks
can be joined by stream copy without decoding them all at once.
"""

import json
import math
import subprocess
from pathlib import Path

import frappe
from frappe import _

# Model names, interpolation multiplier and encoding choices belong to the graph.
_PROFILE = json.loads((Path(__file__).parents[2] / "workflow_adapters/graphs/studio_finish.json").read_text())
STUDIO_SCALE = _PROFILE["execution_spec"]["finishing"]["scale"]
STUDIO_FPS = _PROFILE["execution_spec"]["finishing"]["output_fps"]
CHUNK_FRAMES = _PROFILE["execution_spec"]["finishing"]["chunk_frames"]
RIFE_MULTIPLIER = _PROFILE["execution_spec"]["finishing"]["interpolation_multiplier"]
KEEP_EVERY_NTH = _PROFILE["execution_spec"]["finishing"]["selection_stride"]
CHUNK_TIMEOUT_SECONDS = 900


def studio_profile(profile):
	"""Return the finished delivery profile for a delivery profile (1920x1080 -> 2560x1440 @ 60)."""
	return {
		"width": _even(profile["width"] * _PROFILE["execution_spec"]["finishing"]["delivery_scale"]),
		"height": _even(profile["height"] * _PROFILE["execution_spec"]["finishing"]["delivery_scale"]),
		"fps": float(STUDIO_FPS),
	}


def render_profile(profile):
	"""The profile to render the timeline at before finishing: half the studio size."""
	studio = studio_profile(profile)
	return {
		"width": studio["width"] // STUDIO_SCALE,
		"height": studio["height"] // STUDIO_SCALE,
		"fps": profile["fps"],
	}


def finished_frame_count(frame_count, source_fps):
	return round(frame_count * STUDIO_FPS / source_fps)


def finish_video(source_path, output_path, frame_count, source_fps, temp_path):
	"""Upscale x2 and interpolate source_path (frame_count frames) to STUDIO_FPS."""
	if float(source_fps) != float(_PROFILE["execution_spec"]["finishing"]["source_fps"]):
		raise ValueError("Studio finishing requires the source FPS declared by its workflow profile.")
	temp_path = Path(temp_path)
	chunk_paths = []
	starts = list(range(0, frame_count, CHUNK_FRAMES))
	for index, start in enumerate(starts):
		# Every chunk but the last includes the next chunk's first frame.
		end = min(start + CHUNK_FRAMES, frame_count - 1)
		has_overlap = index < len(starts) - 1
		chunk_source = temp_path / f"chunk-{index:03d}-in.mp4"
		_cut_chunk(source_path, chunk_source, start, end, source_fps)
		chunk_output = temp_path / f"chunk-{index:03d}-out.mp4"
		chunk_output.write_bytes(
			_finish_chunk(chunk_source, finished_chunk_frames(end - start + 1, has_overlap))
		)
		chunk_paths.append(chunk_output)
	_join_chunks(chunk_paths, output_path, finished_frame_count(frame_count, source_fps), temp_path)


def finished_chunk_frames(source_frames, has_overlap):
	"""Frames a chunk keeps after RIFE and frame selection, minus the shared boundary frame."""
	interpolated = (source_frames - 1) * RIFE_MULTIPLIER + 1
	kept = math.ceil(interpolated / KEEP_EVERY_NTH)
	return kept - 1 if has_overlap else kept


def _cut_chunk(source_path, output_path, start, end, fps):
	subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-y",
			"-i",
			str(source_path),
			"-vf",
			f"select='between(n,{start},{end})',setpts=N/{fps:g}/TB",
			"-an",
			"-c:v",
			"libx264",
			"-crf",
			"10",
			"-pix_fmt",
			"yuv420p",
			"-r",
			f"{fps:g}",
			str(output_path),
		],
		check=True,
		capture_output=True,
		timeout=300,
	)


def _finish_chunk(chunk_path, keep_frames):
	from joymedia.services.workflows.capabilities import configured_workflow
	from joymedia.services.workflows.comfyui import run_workflow_to_bytes, upload_local_file
	from joymedia.services.workflows.resolver import build_execution_workflow
	from joymedia.workflow_adapters import get_workflow_adapter

	name = configured_workflow("finishing")
	if not name:
		raise ValueError("Configure a finishing workflow before requesting Studio export.")
	version = frappe.get_doc("Generation Workflow", name)
	from joymedia.services.workflows.capabilities import execution_spec

	if execution_spec(version).get("finishing") != _PROFILE["execution_spec"]["finishing"]:
		raise ValueError(
			"The selected finishing workflow must match the declared Studio timing and scaling contract."
		)
	workflow = build_execution_workflow(
		version,
		inputs={"source_video": upload_local_file(chunk_path)["server_path"]},
		seed=0,
		width=0,
		height=0,
		fps=float(version.output_fps),
		frame_count=keep_frames,
		output_prefix=f"joymedia/finish/{frappe.generate_hash(length=10)}",
	)
	output_node = get_workflow_adapter(version).extract_execution_metadata(workflow)[
		"primary_output_node_key"
	]
	return run_workflow_to_bytes(workflow, output_node, timeout=CHUNK_TIMEOUT_SECONDS, forget=True)


def _join_chunks(chunk_paths, output_path, expected_frames, temp_path):
	"""Join finished chunks by stream copy, then pad or trim to the exact length in one pass.

	Decoding every 1440p chunk at once in a single filter graph exhausts memory.
	"""
	list_path = Path(temp_path) / "chunks.txt"
	list_path.write_text("".join(f"file '{path}'\n" for path in chunk_paths), encoding="utf-8")
	joined = Path(temp_path) / "joined.mp4"
	_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(joined)])
	_ffmpeg(
		[
			"-i",
			str(joined),
			"-vf",
			f"fps={STUDIO_FPS},tpad=stop_mode=clone:stop_duration=1,trim=end_frame={expected_frames}",
			"-an",
			"-c:v",
			"libx264",
			"-profile:v",
			"high",
			"-pix_fmt",
			"yuv420p",
			"-crf",
			"14",
			"-r",
			f"{STUDIO_FPS}",
			"-movflags",
			"+faststart",
			str(output_path),
		]
	)


def _ffmpeg(arguments):
	result = subprocess.run(
		["ffmpeg", "-v", "error", "-y", *arguments], capture_output=True, text=True, timeout=1800
	)
	if result.returncode:
		frappe.throw(
			_("Unable to join finished chunks (ffmpeg exit {0}): {1}").format(
				result.returncode, result.stderr.strip()[-500:]
			)
		)


def _even(value):
	return int(round(value / 2) * 2)
