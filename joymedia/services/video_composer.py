import json
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _


@frappe.whitelist()
def compose_media_specification_from_ui(media_specification_name: str):
	frappe.has_permission("Media Specification", "write", media_specification_name, throw=True)
	result = compose_media_specification(media_specification_name)
	frappe.db.commit()
	return result


def compose_media_specification(media_specification_name: str):
	"""Create a silent, normalized final video from selected shot outputs."""
	media_specification = frappe.get_doc("Media Specification", media_specification_name)
	profile = _get_delivery_profile(media_specification)
	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_specification.name},
		fields=[
			"name",
			"shot_number",
			"duration_seconds",
			"selected_output_asset_version",
			"sound_effect_asset_version",
		],
		order_by="shot_number asc",
	)
	_validate_shots(shots, media_specification.name)
	audio_mixed = False

	try:
		with tempfile.TemporaryDirectory(prefix="joymedia-compose-") as temp_dir:
			temporary_path = Path(temp_dir)
			normalized_paths = []
			for shot in shots:
				source_path = _get_shot_output_path(shot)
				_inspect_video(source_path)
				normalized_path = temporary_path / f"{shot.shot_number:04d}-{shot.name}.mp4"
				_normalize_shot(source_path, normalized_path, profile)
				_validate_normalized_video(normalized_path, profile)
				normalized_paths.append(normalized_path)

			silent_master_path = temporary_path / f"{media_specification.name}-silent.mp4"
			_concatenate_normalized_shots(normalized_paths, silent_master_path, profile)
			_validate_normalized_video(silent_master_path, profile)

			audio_sources = _get_audio_sources(media_specification, shots, normalized_paths)
			delivery_path = silent_master_path
			if audio_sources:
				delivery_path = temporary_path / f"{media_specification.name}.mp4"
				_mix_audio(silent_master_path, audio_sources, delivery_path)
				audio_mixed = True
			_validate_normalized_video(delivery_path, profile)
			video_duration = _get_video_duration(delivery_path)
			video_bytes = delivery_path.read_bytes()
	except (OSError, subprocess.CalledProcessError, ValueError) as exc:
		frappe.throw(_("Unable to compose final video: {0}").format(_command_error(exc)))

	output_asset = _get_or_create_final_asset(media_specification)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{media_specification.name}.mp4",
			"content": video_bytes,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": output_asset.name,
		}
	)
	file_doc.insert(ignore_permissions=True)

	asset_version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": output_asset.name,
			"file": file_doc.file_url,
			"source": "Composed",
			"duration_seconds": video_duration,
			"fps": profile["fps"],
			"notes": (
				"Delivery video composed from normalized selected shot outputs with a global audio mix."
				if audio_mixed
				else "Silent master composed from normalized selected shot outputs."
			),
		}
	)
	asset_version.insert(ignore_permissions=True)

	media_specification.final_asset_version = asset_version.name
	media_specification.save(ignore_permissions=True)
	return {"final_asset_version": asset_version.name}


def _get_delivery_profile(media_specification):
	if not (
		media_specification.delivery_width
		and media_specification.delivery_height
		and media_specification.target_fps
	):
		frappe.throw(_("Media Specification must have delivery width, height, and target FPS before composition."))
	return {
		"width": int(media_specification.delivery_width),
		"height": int(media_specification.delivery_height),
		"fps": float(media_specification.target_fps),
	}


def _validate_shots(shots, media_specification_name):
	if not shots:
		frappe.throw(_("Media Specification {0} has no Shot Specifications.").format(media_specification_name))

	seen_numbers = set()
	for shot in shots:
		if shot.shot_number < 1:
			frappe.throw(_("Shot {0} must have a shot number of at least 1.").format(shot.name))
		if shot.shot_number in seen_numbers:
			frappe.throw(_("Shot number {0} is duplicated in this Media Specification.").format(shot.shot_number))
		seen_numbers.add(shot.shot_number)
		if not shot.selected_output_asset_version:
			frappe.throw(_("Shot {0} has no selected output asset version.").format(shot.name))


def _get_shot_output_path(shot):
	asset_version = frappe.get_doc("Asset Version", shot.selected_output_asset_version)
	media_asset = frappe.get_doc("Media Asset", asset_version.media_asset)
	if media_asset.media_type != "Video":
		frappe.throw(_("Shot {0} selected output must be a video Asset Version.").format(shot.name))
	if not asset_version.file:
		frappe.throw(_("Asset Version {0} has no attached file.").format(asset_version.name))

	file_doc = frappe.get_doc("File", {"file_url": asset_version.file})
	path = Path(file_doc.get_full_path())
	if not path.exists():
		frappe.throw(_("Asset Version file does not exist: {0}").format(path))
	return path


def _get_audio_sources(media_specification, shots, normalized_paths):
	sources = []
	if media_specification.global_bgm_asset_version:
		sources.append(
			{
				"path": _get_audio_asset_path(media_specification.global_bgm_asset_version),
				"start_seconds": 0,
				"loop": True,
			}
		)
	if media_specification.voiceover_asset_version:
		sources.append(
			{
				"path": _get_audio_asset_path(media_specification.voiceover_asset_version),
				"start_seconds": 0,
				"loop": False,
			}
		)

	shot_start_seconds = 0
	for shot, normalized_path in zip(shots, normalized_paths, strict=True):
		if shot.sound_effect_asset_version:
			sources.append(
				{
					"path": _get_audio_asset_path(shot.sound_effect_asset_version),
					"start_seconds": shot_start_seconds,
					"loop": False,
				}
			)
		shot_start_seconds += _get_video_duration(normalized_path)
	return sources


def _get_audio_asset_path(asset_version_name):
	asset_version = frappe.get_doc("Asset Version", asset_version_name)
	media_asset = frappe.get_doc("Media Asset", asset_version.media_asset)
	if media_asset.media_type != "Audio":
		frappe.throw(_("Asset Version {0} must belong to an Audio Media Asset.").format(asset_version.name))
	if not asset_version.file:
		frappe.throw(_("Asset Version {0} has no attached file.").format(asset_version.name))

	file_doc = frappe.get_doc("File", {"file_url": asset_version.file})
	path = Path(file_doc.get_full_path())
	if not path.exists():
		frappe.throw(_("Asset Version file does not exist: {0}").format(path))
	if not _has_audio_stream(path):
		frappe.throw(_("Asset Version {0} has no audio stream.").format(asset_version.name))
	return path


def _normalize_shot(source_path, normalized_path, profile):
	video_filter = (
		f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=decrease,"
		f"pad={profile['width']}:{profile['height']}:(ow-iw)/2:(oh-ih)/2,fps={profile['fps']:g}"
	)
	_run_ffmpeg(
		[
			"ffmpeg",
			"-y",
			"-i",
			str(source_path),
			"-map",
			"0:v:0",
			"-vf",
			video_filter,
			"-an",
			"-c:v",
			"libx264",
			"-profile:v",
			"high",
			"-pix_fmt",
			"yuv420p",
			"-movflags",
			"+faststart",
			str(normalized_path),
		]
	)


def _concatenate_normalized_shots(paths, output_path, profile):
	concat_file = output_path.with_suffix(".txt")
	concat_file.write_text("\n".join(f"file '{_escape_concat_path(path)}'" for path in paths) + "\n")
	_run_ffmpeg(
		[
			"ffmpeg",
			"-y",
			"-f",
			"concat",
			"-safe",
			"0",
			"-i",
			str(concat_file),
			"-map",
			"0:v:0",
			"-an",
			"-c:v",
			"libx264",
			"-profile:v",
			"high",
			"-pix_fmt",
			"yuv420p",
			"-r",
			f"{profile['fps']:g}",
			"-movflags",
			"+faststart",
			str(output_path),
		]
	)


def _mix_audio(silent_master_path, audio_sources, delivery_path):
	video_duration = _get_video_duration(silent_master_path)
	command = ["ffmpeg", "-y", "-i", str(silent_master_path)]
	filter_parts = []
	input_labels = []
	for index, source in enumerate(audio_sources, start=1):
		if source["loop"]:
			command.extend(["-stream_loop", "-1"])
		command.extend(["-i", str(source["path"])])

		filter = f"[{index}:a]atrim=duration={video_duration:.6f}"
		if source["start_seconds"]:
			filter += f",adelay={round(source['start_seconds'] * 1000)}:all=1"
		filter_parts.append(f"{filter}[audio{index}]")
		input_labels.append(f"[audio{index}]")

	filter_parts.append(
		"".join(input_labels)
		+ f"amix=inputs={len(input_labels)}:duration=longest:normalize=1,atrim=duration={video_duration:.6f}[mixed]"
	)
	command.extend(
		[
			"-filter_complex",
			";".join(filter_parts),
			"-map",
			"0:v:0",
			"-map",
			"[mixed]",
			"-c:v",
			"libx264",
			"-profile:v",
			"high",
			"-pix_fmt",
			"yuv420p",
			"-c:a",
			"aac",
			"-b:a",
			"192k",
			"-movflags",
			"+faststart",
			str(delivery_path),
		]
	)
	_run_ffmpeg(command)


def _inspect_video(path):
	result = subprocess.run(
		[
			"ffprobe",
			"-v",
			"error",
			"-select_streams",
			"v:0",
			"-show_entries",
			"stream=codec_name,profile,width,height,pix_fmt,r_frame_rate",
			"-of",
			"json",
			str(path),
		],
		capture_output=True,
		text=True,
		check=True,
	)
	streams = json.loads(result.stdout).get("streams", [])
	if not streams:
		raise ValueError(f"{path} does not contain a video stream")
	return streams[0]


def _get_video_duration(path):
	result = subprocess.run(
		[
			"ffprobe",
			"-v",
			"error",
			"-show_entries",
			"format=duration",
			"-of",
			"json",
			str(path),
		],
		capture_output=True,
		text=True,
		check=True,
	)
	return float(json.loads(result.stdout)["format"]["duration"])


def _has_audio_stream(path):
	result = subprocess.run(
		[
			"ffprobe",
			"-v",
			"error",
			"-select_streams",
			"a:0",
			"-show_entries",
			"stream=codec_type",
			"-of",
			"json",
			str(path),
		],
		capture_output=True,
		text=True,
		check=True,
	)
	return bool(json.loads(result.stdout).get("streams"))


def _validate_normalized_video(path, profile):
	stream = _inspect_video(path)
	if (
		stream.get("codec_name") != "h264"
		or stream.get("profile") != "High"
		or stream.get("pix_fmt") != "yuv420p"
		or stream.get("width") != profile["width"]
		or stream.get("height") != profile["height"]
		or abs(_frame_rate(stream.get("r_frame_rate")) - profile["fps"]) > 0.001
	):
		raise ValueError(f"{path} does not match the normalized delivery profile")


def _frame_rate(value):
	try:
		numerator, denominator = str(value).split("/", 1)
		return int(numerator) / int(denominator)
	except (TypeError, ValueError, ZeroDivisionError) as exc:
		raise ValueError(f"Invalid video frame rate: {value}") from exc


def _get_or_create_final_asset(media_specification):
	asset_name = f"{media_specification.name} Final Video"
	asset_id = frappe.db.get_value("Media Asset", {"asset_name": asset_name}, "name")
	if asset_id:
		return frappe.get_doc("Media Asset", asset_id)

	output_asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": asset_name,
			"asset_scope": "Project",
			"media_type": "Video",
			"asset_category": "Final Deliverable",
			"media_project": media_specification.media_project,
		}
	)
	output_asset.insert(ignore_permissions=True)
	return output_asset


def _run_ffmpeg(command):
	subprocess.run(command, capture_output=True, text=True, check=True)


def _escape_concat_path(path):
	return str(path).replace("'", "'\\''")


def _command_error(exc):
	if isinstance(exc, subprocess.CalledProcessError):
		return exc.stderr.strip() or str(exc)
	return str(exc)
