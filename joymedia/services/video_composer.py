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

			audio_sources = _get_audio_sources(media_specification, _get_video_duration(silent_master_path))
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
		}
	)
	asset_version.insert(ignore_permissions=True)

	media_specification.final_asset_version = asset_version.name
	media_specification.save(ignore_permissions=True)
	return {"final_asset_version": asset_version.name}


def _get_delivery_profile(media_specification):
	if not media_specification.delivery_width or not media_specification.delivery_height:
		frappe.throw(_("Media Specification must have delivery width and height before composition."))
	if not media_specification.workflow:
		frappe.throw(_("Media Specification must have a Workflow before composition."))

	workflow_version = frappe.get_doc(
		"Workflow",
		media_specification.workflow,
	)
	if not workflow_version.output_fps:
		frappe.throw(_("Workflow must have output FPS before composition."))

	return {
		"width": int(media_specification.delivery_width),
		"height": int(media_specification.delivery_height),
		"fps": float(workflow_version.output_fps),
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


def _get_audio_sources(media_specification, video_duration):
	sources = []
	for cue in media_specification.get("audio_cues") or []:
		start_seconds = float(cue.start_seconds or 0)
		end_seconds = min(float(cue.end_seconds or video_duration), video_duration)
		if start_seconds >= video_duration:
			frappe.throw(_("Audio Cue {0} starts after the composed video ends.").format(cue.idx))
		if end_seconds <= start_seconds:
			frappe.throw(_("Audio Cue {0} has no usable timeline duration.").format(cue.idx))
		cue_duration = end_seconds - start_seconds
		fade_in_seconds = float(cue.fade_in_seconds or 0)
		fade_out_seconds = float(cue.fade_out_seconds or 0)
		if fade_in_seconds + fade_out_seconds > cue_duration:
			frappe.throw(_("Audio Cue {0} fades exceed its timeline duration.").format(cue.idx))
		sources.append(
			{
				"path": _get_audio_asset_path(cue.asset_version),
				"start_seconds": start_seconds,
				"duration_seconds": cue_duration,
				"gain_db": float(cue.gain_db or 0),
				"fade_in_seconds": fade_in_seconds,
				"fade_out_seconds": fade_out_seconds,
				"duck_others": bool(cue.duck_others),
				"loop": cue.role == "BGM",
			}
		)
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
	command = ["ffmpeg", "-y", "-i", str(silent_master_path)]
	filter_parts = []
	duck_labels = []
	base_labels = []
	for index, source in enumerate(audio_sources, start=1):
		if source["loop"]:
			command.extend(["-stream_loop", "-1"])
		command.extend(["-i", str(source["path"])])

		filter = f"[{index}:a]atrim=duration={source['duration_seconds']:.6f},asetpts=PTS-STARTPTS"
		filter += f",volume={source['gain_db']:.6f}dB"
		if source["fade_in_seconds"]:
			filter += f",afade=t=in:st=0:d={source['fade_in_seconds']:.6f}"
		if source["fade_out_seconds"]:
			fade_start = source["duration_seconds"] - source["fade_out_seconds"]
			filter += f",afade=t=out:st={fade_start:.6f}:d={source['fade_out_seconds']:.6f}"
		if source["start_seconds"]:
			filter += f",adelay={round(source['start_seconds'] * 1000)}:all=1"
		filter_parts.append(f"{filter}[audio{index}]")
		(duck_labels if source["duck_others"] else base_labels).append(f"[audio{index}]")

	if duck_labels:
		_mix_labels(filter_parts, duck_labels, "duck_source")
		if base_labels:
			_mix_labels(filter_parts, base_labels, "base")
			filter_parts.append("[duck_source]asplit=2[duck_sidechain][duck_mix]")
			filter_parts.append("[base][duck_sidechain]sidechaincompress[ducked]")
			_mix_labels(filter_parts, ["[ducked]", "[duck_mix]"], "mixed")
		else:
			filter_parts.append("[duck_source]anull[mixed]")
	else:
		_mix_labels(filter_parts, base_labels, "mixed")
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


def _mix_labels(filter_parts, labels, output_label):
	if len(labels) == 1:
		filter_parts.append(f"{labels[0]}anull[{output_label}]")
		return
	filter_parts.append(
		"".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0[{output_label}]"
	)


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
