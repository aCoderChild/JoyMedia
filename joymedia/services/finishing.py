"""Studio finishing: Real-ESRGAN x2 upscaling and RIFE interpolation to 60 fps.

The film is rendered at half the target size, cut into one-second chunks and
finished on ComfyUI chunk by chunk, so GPU memory stays bounded. Each chunk
carries the next chunk's first frame, so RIFE also interpolates across chunk
boundaries; ComfyUI drops that duplicate frame again, so the finished chunks
can be joined by stream copy without decoding them all at once.
"""

import math

import subprocess
from pathlib import Path

import frappe
from frappe import _

STUDIO_SCALE = 2
STUDIO_FPS = 60
CHUNK_FRAMES = 24
# RIFE renders 120 fps (x5) and every second frame is kept: 24 fps -> 60 fps.
RIFE_MULTIPLIER = 5
KEEP_EVERY_NTH = 2
UPSCALE_MODEL = "RealESRGAN_x2.pth"
INTERPOLATION_MODEL = "rife_v4.26.safetensors"
CHUNK_TIMEOUT_SECONDS = 900
OUTPUT_NODE = "joymedia_save"


def studio_profile(profile):
	"""Return the finished delivery profile for a delivery profile (1920x1080 -> 2560x1440 @ 60)."""
	return {
		"width": _even(profile["width"] * 4 / 3),
		"height": _even(profile["height"] * 4 / 3),
		"fps": float(STUDIO_FPS),
	}


def render_profile(profile):
	"""The profile to render the timeline at before finishing: half the studio size."""
	studio = studio_profile(profile)
	return {"width": studio["width"] // STUDIO_SCALE, "height": studio["height"] // STUDIO_SCALE, "fps": profile["fps"]}


def finished_frame_count(frame_count, source_fps):
	return round(frame_count * STUDIO_FPS / source_fps)


def finish_video(source_path, output_path, frame_count, source_fps, temp_path):
	"""Upscale x2 and interpolate source_path (frame_count frames) to STUDIO_FPS."""
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
		chunk_output.write_bytes(_finish_chunk(chunk_source, finished_chunk_frames(end - start + 1, has_overlap)))
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
			"ffmpeg", "-v", "error", "-y", "-i", str(source_path),
			"-vf", f"select='between(n,{start},{end})',setpts=N/{fps:g}/TB",
			"-an", "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", "-r", f"{fps:g}",
			str(output_path),
		],
		check=True, capture_output=True, timeout=300,
	)


def _finish_chunk(chunk_path, keep_frames):
	from joymedia.services.comfyui_client import run_workflow_to_bytes, upload_local_file

	workflow = {
		"load": {
			"class_type": "VHS_LoadVideo",
			"inputs": {
				"video": upload_local_file(chunk_path)["server_path"],
				"force_rate": 0, "custom_width": 0, "custom_height": 0, "frame_load_cap": 0,
				"skip_first_frames": 0, "select_every_nth": 1, "format": "None",
			},
		},
		"upscale_model": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALE_MODEL}},
		"upscale": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["upscale_model", 0], "image": ["load", 0]}},
		"interp_model": {"class_type": "FrameInterpolationModelLoader", "inputs": {"model_name": INTERPOLATION_MODEL}},
		"interpolate": {
			"class_type": "FrameInterpolate",
			"inputs": {"interp_model": ["interp_model", 0], "images": ["upscale", 0], "multiplier": RIFE_MULTIPLIER},
		},
		"select": {
			"class_type": "VHS_SelectEveryNthImage",
			"inputs": {"images": ["interpolate", 0], "select_every_nth": KEEP_EVERY_NTH, "skip_first_images": 0},
		},
		"trim": {
			"class_type": "ImageFromBatch",
			"inputs": {"image": ["select", 0], "batch_index": 0, "length": keep_frames},
		},
		OUTPUT_NODE: {
			"class_type": "VHS_VideoCombine",
			"inputs": {
				"images": ["trim", 0], "frame_rate": float(STUDIO_FPS), "loop_count": 0,
				"filename_prefix": f"joymedia/finish/{frappe.generate_hash(length=10)}",
				"format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 12,
				# Chunks are intermediate: ComfyUI's temp folder is cleared on restart,
				# while its output folder would keep ~220 MB per Studio export.
				"save_metadata": False, "pingpong": False, "save_output": False,
			},
		},
	}
	return run_workflow_to_bytes(workflow, OUTPUT_NODE, timeout=CHUNK_TIMEOUT_SECONDS, forget=True)


def _join_chunks(chunk_paths, output_path, expected_frames, temp_path):
	"""Join finished chunks by stream copy, then pad or trim to the exact length in one pass.

	Decoding every 1440p chunk at once in a single filter graph exhausts memory.
	"""
	list_path = Path(temp_path) / "chunks.txt"
	list_path.write_text("".join(f"file '{path}'\n" for path in chunk_paths), encoding="utf-8")
	joined = Path(temp_path) / "joined.mp4"
	_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(joined)])
	_ffmpeg([
		"-i", str(joined),
		"-vf", f"fps={STUDIO_FPS},tpad=stop_mode=clone:stop_duration=1,trim=end_frame={expected_frames}",
		"-an", "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", "14",
		"-r", f"{STUDIO_FPS}", "-movflags", "+faststart", str(output_path),
	])


def _ffmpeg(arguments):
	result = subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], capture_output=True, text=True, timeout=1800)
	if result.returncode:
		frappe.throw(
			_("Unable to join finished chunks (ffmpeg exit {0}): {1}").format(
				result.returncode, result.stderr.strip()[-500:]
			)
		)


def _frame_count(path):
	output = subprocess.run(
		["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
		 "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
		capture_output=True, text=True, check=True, timeout=120,
	).stdout.strip()
	return int(output)


def _even(value):
	return int(round(value / 2) * 2)
