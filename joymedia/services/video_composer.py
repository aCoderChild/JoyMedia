import json
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _
from frappe.utils.synchronization import filelock


def compose_shot_segments(generation_run_name, shot_name):
	"""Assemble completed generated segments into one selected Shot output."""
	with filelock(f"joymedia-compose-shot-{generation_run_name}-{shot_name}"):
		shot = frappe.get_doc("Shot", shot_name)
		jobs = frappe.get_all(
			"Generation Task",
			filters={
				"generation_run": generation_run_name,
				"shot": shot.name,
			},
			fields=["name", "segment_index", "segment_frame_count", "status"],
			order_by="segment_index asc",
		)
		if not jobs or any(job.status != "Completed" for job in jobs):
			return None

		project = frappe.get_doc("Media Project", shot.media_project)
		segments = []
		for job in jobs:
			attempt = frappe.db.get_value(
				"Generation Attempt",
				{"generation_task": job.name, "status": "Completed"},
				"name",
				order_by="creation desc",
			)
			if not attempt:
				return None
			artifact = frappe.get_doc(
				"Generation Artifact",
				{"generation_attempt": attempt, "artifact_role": "Primary Video"},
			)
			if not artifact.frappe_file:
				return None
			segments.append((job, artifact))

		shot_asset = _get_or_create_shot_output_asset(shot, project.name)
		if len(segments) == 1:
			artifact = segments[0][1]
			promoted_file = _promote_artifact_file(
				artifact,
				shot_asset,
				f"{shot.name}.mp4",
			)
			asset_version = frappe.get_doc(
				{
					"doctype": "Asset Version",
					"media_asset": shot_asset.name,
					"file": promoted_file.file_url,
					"source": "Generated",
				}
			).insert(ignore_permissions=True)
			shot.db_set("selected_output_asset_version", asset_version.name, update_modified=False)
			return asset_version.name

		profile = _get_delivery_profile(project, generation_run_name)
		try:
			with tempfile.TemporaryDirectory(prefix=f"joymedia-shot-{shot.name}-") as temp_dir:
				temporary_path = Path(temp_dir)
				normalized_paths = []
				expected_frames = 0
				for index, (job, artifact) in enumerate(segments):
					generated_frames = int(job.segment_frame_count or 0)
					effective_frames = generated_frames if index == 0 else generated_frames - 1
					if effective_frames <= 0:
						raise ValueError(f"Generation Task {job.name} has no effective segment frames")
					normalized_path = temporary_path / f"{index + 1:04d}-{job.name}.mp4"
					_normalize_segment(
						_get_artifact_path(artifact),
						normalized_path,
						profile,
						generated_frames,
						drop_first=index > 0,
					)
					_validate_normalized_video(normalized_path, profile, expected_frames=effective_frames)
					normalized_paths.append(normalized_path)
					expected_frames += effective_frames

				assembled_path = temporary_path / f"{shot.name}.mp4"
				_concatenate_normalized_shots(normalized_paths, assembled_path, profile)
				_validate_normalized_video(assembled_path, profile, expected_frames=expected_frames)
				video_bytes = assembled_path.read_bytes()
				video_duration = _get_video_duration(assembled_path)
		except (OSError, subprocess.CalledProcessError, ValueError) as exc:
			frappe.throw(_("Unable to assemble Shot segments: {0}").format(_command_error(exc)))

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{shot.name}.mp4",
				"content": video_bytes,
				"is_private": 1,
				"attached_to_doctype": "Media Asset",
				"attached_to_name": shot_asset.name,
			}
		).insert(ignore_permissions=True)
		asset_version = frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": shot_asset.name,
				"file": file_doc.file_url,
				"source": "Composed",
				"duration_seconds": video_duration,
				"fps": profile["fps"],
			}
		).insert(ignore_permissions=True)
		shot.db_set("selected_output_asset_version", asset_version.name, update_modified=False)
		return asset_version.name


def _promote_artifact_file(artifact, media_asset, file_name):
	"""Copy an internal artifact file into the customer-visible asset library."""
	source_file = frappe.get_doc("File", {"file_url": artifact.frappe_file})
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": source_file.get_content(),
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": media_asset.name,
		}
	).insert(ignore_permissions=True)


def _get_or_create_shot_output_asset(shot, media_project):
	asset_name = f"{shot.name} Output"
	asset_id = frappe.db.get_value(
		"Media Asset",
		{
			"asset_name": asset_name,
			"media_project": media_project,
			"asset_category": "Other",
			"asset_scope": "Project Output",
		},
		"name",
	)
	if asset_id:
		return frappe.get_doc("Media Asset", asset_id)
	return frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": asset_name,
			"media_project": media_project,
			"media_type": "Video",
			"asset_category": "Other",
			"asset_scope": "Project Output",
			"status": "Active",
		}
	).insert(ignore_permissions=True)



def _get_delivery_profile(project, generation_run_name=None):
	width = project.delivery_width
	height = project.delivery_height
	workflow_name = project.workflow
	if generation_run_name:
		run = frappe.get_doc("Generation Run", generation_run_name)
		try:
			snapshot = frappe.parse_json(run.project_snapshot_json or "{}")
		except (TypeError, ValueError):
			frappe.throw(_("Generation Run {0} has invalid project snapshot JSON.").format(run.name))
		width = snapshot.get("delivery_width")
		height = snapshot.get("delivery_height")
		workflow_name = snapshot.get("workflow") or run.workflow
	if not width or not height:
		frappe.throw(_("Media Project must have delivery width and height before composition."))
	if not workflow_name:
		frappe.throw(_("Media Project must have a Workflow before composition."))

	workflow = frappe.get_doc(
		"Generation Workflow",
		workflow_name,
	)
	if not workflow.output_fps:
		frappe.throw(_("Workflow must have output FPS before composition."))

	return {
		"width": int(width),
		"height": int(height),
		"fps": float(workflow.output_fps),
	}


def _shot_frame_count(shot, profile):
	"""Return the persisted frame-exact duration used by the editor/exporter."""
	planned_frames = int(shot.get("planned_frame_count") or 0)
	if planned_frames > 0:
		return planned_frames

	duration_seconds = float(shot.get("duration_seconds") or 0)
	frames = round(duration_seconds * profile["fps"])
	if frames <= 0:
		raise ValueError(f"Shot {shot.name} has no positive timeline duration")
	return frames


def _validate_shots(shots, media_project_name):
	if not shots:
		frappe.throw(_("Media Project {0} has no Shots.").format(media_project_name))

	seen_numbers = set()
	for shot in shots:
		if shot.shot_number < 1:
			frappe.throw(_("Shot {0} must have a shot number of at least 1.").format(shot.name))
		if shot.shot_number in seen_numbers:
			frappe.throw(_("Shot number {0} is duplicated in this Media Project.").format(shot.shot_number))
		seen_numbers.add(shot.shot_number)
		if not shot.selected_output_asset_version:
			frappe.throw(_("Shot {0} has no selected output asset version.").format(shot.name))
		if float(shot.duration_seconds or 0) <= 0 and int(shot.planned_frame_count or 0) <= 0:
			frappe.throw(_("Shot {0} has no positive timeline duration.").format(shot.name))


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


def _get_audio_sources(project, video_duration, timeline_clips=None, fps=None):
	sources = []
	if timeline_clips is None:
		return sources
	fps = float(fps or 0)
	if fps <= 0:
		frappe.throw(_("Workflow output FPS must be greater than zero."))
	for clip in timeline_clips:
		start_seconds = float(clip.timeline_start_frame or 0) / fps
		clip_frames = int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0)
		end_seconds = min(start_seconds + clip_frames / fps, video_duration)
		if start_seconds >= video_duration:
			frappe.throw(_("Audio clip {0} starts after the composed video ends.").format(clip.name))
		if end_seconds <= start_seconds:
			frappe.throw(_("Audio clip {0} has no usable timeline duration.").format(clip.name))
		cue_duration = end_seconds - start_seconds
		fade_in_seconds = float(clip.fade_in_frames or 0) / fps
		fade_out_seconds = float(clip.fade_out_frames or 0) / fps
		if fade_in_seconds + fade_out_seconds > cue_duration:
			frappe.throw(_("Audio clip {0} fades exceed its timeline duration.").format(clip.name))
		sources.append(
			{
				"path": _get_audio_asset_path(clip.source_asset_version),
				"start_seconds": start_seconds,
				"duration_seconds": cue_duration,
				"gain_db": float(clip.gain_db or 0),
				"fade_in_seconds": fade_in_seconds,
				"fade_out_seconds": fade_out_seconds,
				"duck_others": bool(clip.duck_others),
				"loop": clip.audio_role == "BGM",
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


def _normalize_shot(source_path, normalized_path, profile, planned_frames):
	"""Normalize one clip and force it to the exact editor frame count.

	The generated source may be longer or shorter than the edited timeline clip.
	Long clips are trimmed. Short clips are padded by holding the final frame,
	which makes the existing UI's Extend action deterministic instead of silently
	being ignored by the final composition step.
	"""
	if planned_frames <= 0:
		raise ValueError("Shot planned frame count must be greater than zero")

	planned_duration = planned_frames / profile["fps"]
	video_filter = (
		f"fps={profile['fps']:g},"
		f"tpad=stop_mode=clone:stop_duration={planned_duration:.6f},"
		f"trim=end_frame={planned_frames},setpts=PTS-STARTPTS,"
		f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=decrease,"
		f"pad={profile['width']}:{profile['height']}:(ow-iw)/2:(oh-ih)/2"
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


def _normalize_segment(source_path, normalized_path, profile, generated_frames, *, drop_first):
	"""Normalize a generated segment and remove its continuation overlap frame."""
	effective_frames = generated_frames - 1 if drop_first else generated_frames
	video_filter = f"fps={profile['fps']:g},"
	if drop_first:
		video_filter += "select='not(eq(n,0))',"
	video_filter += (
		f"tpad=stop_mode=clone:stop_duration={effective_frames / profile['fps']:.6f},"
		f"trim=end_frame={effective_frames},setpts=PTS-STARTPTS,"
		f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=decrease,"
		f"pad={profile['width']}:{profile['height']}:(ow-iw)/2:(oh-ih)/2"
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


def _get_asset_version_path(asset_version_name):
	asset_version = frappe.get_doc("Asset Version", asset_version_name)
	if not asset_version.file:
		raise ValueError(f"Asset Version {asset_version.name} has no file")
	file_doc = frappe.get_doc("File", {"file_url": asset_version.file})
	path = Path(file_doc.get_full_path())
	if not path.exists():
		raise ValueError(f"Asset Version file does not exist: {path}")
	return path


def _get_artifact_path(artifact):
	if not artifact.frappe_file:
		raise ValueError(f"Generation Artifact {artifact.name} has no file")
	file_doc = frappe.get_doc("File", {"file_url": artifact.frappe_file})
	path = Path(file_doc.get_full_path())
	if not path.exists():
		raise ValueError(f"Generation Artifact file does not exist: {path}")
	return path


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


def _validate_normalized_video(path, profile, expected_frames=None):
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

	if expected_frames is not None:
		expected_duration = expected_frames / profile["fps"]
		actual_duration = _get_video_duration(path)
		frame_tolerance = (1 / profile["fps"]) + 0.01
		if abs(actual_duration - expected_duration) > frame_tolerance:
			raise ValueError(
				f"{path} duration {actual_duration:.6f}s does not match timeline "
				f"duration {expected_duration:.6f}s"
			)


def _frame_rate(value):
	try:
		numerator, denominator = str(value).split("/", 1)
		return int(numerator) / int(denominator)
	except (TypeError, ValueError, ZeroDivisionError) as exc:
		raise ValueError(f"Invalid video frame rate: {value}") from exc


def _get_or_create_final_asset(project):
	asset_name = f"{project.name} Final Video"
	asset_id = frappe.db.get_value(
		"Media Asset",
		{"asset_name": asset_name, "media_project": project.name},
		"name",
	)
	if asset_id:
		return frappe.get_doc("Media Asset", asset_id)

	output_asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"asset_name": asset_name,
			"media_project": project.name,
			"media_type": "Video",
			"asset_category": "Other",
			"asset_scope": "Project Output",
			"status": "Active",
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
