"""Render the persistent JoyMedia Timeline Clip edit decision list."""

import shutil
import tempfile
from pathlib import Path

import frappe
from frappe import _

from joymedia.services import finishing
from joymedia.services.video_composer import (
	_get_audio_sources,
	_get_or_create_final_asset,
	_get_video_duration,
	_mix_audio,
	_run_ffmpeg,
	_has_audio_stream,
	_validate_normalized_video,
)


STUDIO_EXPORT_QUALITY = "Studio 1440p60"
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
END_CARD_SECONDS = 3.5
# Every film fades to black, and its sound to silence, over its last second.
ENDING_FADE_SECONDS = 1.0
TITLE_FONT = "PlayfairDisplay.ttf"
TAGLINE_FONT = "GreatVibes-Regular.ttf"

TRANSITION_FILTERS = {
	"Dissolve": "fade",
	"Fade": "fadeblack",
}


def compose_project_timeline_internal(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	from joymedia.services.timeline_editor import _ensure_source_audio_clips, _timeline_clip_rows
	_timeline_rows = _timeline_clip_rows(project.name)
	_ensure_source_audio_clips(project, _timeline_rows)
	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project.name, "enabled": 1},
		fields=[
			"name",
			"clip_order",
			"track_type",
			"track_index",
			"timeline_start_frame",
			"audio_role",
			"gain_db",
			"fade_in_frames",
			"fade_out_frames",
			"duck_others",
			"source_asset_version",
			"source_in_frame",
			"source_out_frame",
			"transition_to_next",
			"transition_frames",
		],
		order_by="clip_order asc, creation asc",
	)
	video_clips = [clip for clip in clips if (clip.track_type or "Video") == "Video"]
	audio_clips = [clip for clip in clips if clip.track_type == "Audio"]
	if not video_clips:
		frappe.throw(_("The project timeline has no enabled clips."))
	if any(int(clip.track_index or 0) != 0 for clip in video_clips):
		frappe.throw(_("Timeline export currently supports one video track (Video 0)."))
	video_clips.sort(key=lambda clip: (int(clip.timeline_start_frame or 0), int(clip.clip_order or 0)))

	profile = _delivery_profile(project)
	studio = (project.get("export_quality") or "") == STUDIO_EXPORT_QUALITY
	# Studio exports render at half size and are upscaled and interpolated afterwards.
	render = finishing.render_profile(profile) if studio else profile
	output_profile = finishing.studio_profile(profile) if studio else profile
	clip_frames = [int(clip.source_out_frame) - int(clip.source_in_frame) for clip in video_clips]
	if any(frames <= 0 for frames in clip_frames):
		frappe.throw(_("Every timeline clip must contain at least one frame."))

	transition_frames = _validated_transition_frames(video_clips, clip_frames)
	positioned = _has_persisted_positions(video_clips) and _requires_positioned_render(video_clips, clip_frames)
	if positioned:
		for previous, current, previous_frames in zip(video_clips, video_clips[1:], clip_frames):
			previous_end = int(previous.timeline_start_frame or 0) + previous_frames
			if int(current.timeline_start_frame or 0) < previous_end:
				frappe.throw(_("Video clips may not overlap on the single video track."))
		expected_frames = max(
			int(clip.timeline_start_frame or 0) + frames
			for clip, frames in zip(video_clips, clip_frames)
		)
	else:
		expected_frames = sum(clip_frames) - sum(transition_frames)

	try:
		with tempfile.TemporaryDirectory(prefix="joymedia-timeline-") as temp_dir:
			temp_path = Path(temp_dir)
			normalized_paths = []
			for index, (clip, frame_count) in enumerate(zip(video_clips, clip_frames), start=1):
				source_path = _asset_version_path(clip.source_asset_version)
				normalized_path = temp_path / f"{index:04d}-{clip.name}.mp4"
				_normalize_clip(
					source_path,
					normalized_path,
					render,
					int(clip.source_in_frame),
					int(clip.source_out_frame),
				)
				_validate_normalized_video(normalized_path, render, expected_frames=frame_count)
				normalized_paths.append(normalized_path)

			silent_master = temp_path / f"{project.name}-timeline-silent.mp4"
			_render_sequence(
				normalized_paths,
				video_clips,
				clip_frames,
				transition_frames,
				silent_master,
				render,
				positioned=positioned,
			)
			_validate_normalized_video(silent_master, render, expected_frames=expected_frames)
			output_frames = expected_frames
			if studio:
				finished_master = temp_path / f"{project.name}-timeline-studio.mp4"
				finishing.finish_video(silent_master, finished_master, expected_frames, render["fps"], temp_path)
				output_frames = finishing.finished_frame_count(expected_frames, render["fps"])
				_validate_normalized_video(finished_master, output_profile, expected_frames=output_frames)
				silent_master = finished_master
			title = (project.get("end_card_title") or "").strip()
			tagline = (project.get("end_card_tagline") or "").strip()
			ended_master = temp_path / f"{project.name}-timeline-ending.mp4"
			_apply_ending(silent_master, ended_master, output_profile, title, tagline, temp_path)
			_validate_normalized_video(ended_master, output_profile, expected_frames=output_frames)
			silent_master = ended_master

			delivery_path = silent_master
			video_duration = _get_video_duration(silent_master)
			audio_sources = _get_audio_sources(
				project, video_duration, audio_clips, profile["fps"]
			)
			if audio_sources:
				delivery_path = temp_path / f"{project.name}-timeline.mp4"
				_mix_audio(
					silent_master, audio_sources, delivery_path,
					ending=(max(0.0, video_duration - ENDING_FADE_SECONDS), ENDING_FADE_SECONDS),
				)
				_validate_normalized_video(delivery_path, output_profile, expected_frames=output_frames)

			video_duration = _get_video_duration(delivery_path)
			# Studio exports exceed the upload size limit, which is meant for user
			# uploads; the rendered file is moved into place instead of re-read.
			file_name = f"{project.name}-edited-{frappe.generate_hash(length=8)}.mp4"
			stored_path = Path(frappe.get_site_path("private", "files", file_name))
			shutil.move(str(delivery_path), stored_path)
	except (OSError, ValueError) as exc:
		frappe.throw(_("Unable to render timeline: {0}").format(str(exc)))
	except Exception as exc:
		# subprocess.CalledProcessError is intentionally folded into a readable
		# editor error without exposing a raw Python traceback to the client.
		stderr = getattr(exc, "stderr", None)
		frappe.throw(_("Unable to render timeline: {0}").format((stderr or str(exc)).strip()))

	# The render took minutes; MariaDB's snapshot isolation rejects writes to rows
	# (such as naming series) that other workers changed since this transaction began.
	frappe.db.commit()
	output_asset = _get_or_create_final_asset(project)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"file_url": f"/private/files/{file_name}",
			"file_size": stored_path.stat().st_size,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": output_asset.name,
		}
	)
	file_doc.flags.copy_from_existing_file = True
	file_doc.insert(ignore_permissions=True)

	asset_version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": output_asset.name,
			"file": file_doc.file_url,
			"source": "Edited",
			"duration_seconds": video_duration,
			"fps": output_profile["fps"],
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value(
		"Media Project",
		project.name,
		"current_output_asset_version",
		asset_version.name,
		update_modified=False,
	)

	return {
		"current_output_asset_version": asset_version.name,
		"file": file_doc.file_url,
		"duration_seconds": video_duration,
		"timeline_frames": expected_frames,
		"fps": output_profile["fps"],
	}


def _apply_ending(source_path, output_path, profile, title, tagline, temp_path):
	"""End the film: fade any title and tagline in, then fade the picture to black."""
	duration = _get_video_duration(source_path)
	start = max(0.0, duration - min(END_CARD_SECONDS, duration * 0.4))
	height = profile["height"]
	filters = []
	# Text goes through files so quotes, colons and accents need no escaping.
	for index, (text, font, size, delay, offset) in enumerate((
		(title, TITLE_FONT, round(height * 0.1), 0.0, -0.06 if tagline else 0.0),
		(tagline, TAGLINE_FONT, round(height * 0.072), 0.5, 0.07 if title else 0.0),
	)):
		if not text:
			continue
		text_file = temp_path / f"end-card-{index}.txt"
		text_file.write_text(text, encoding="utf-8")
		appear = start + delay
		filters.append(
			f"drawtext=fontfile='{FONT_DIR / font}':textfile='{text_file}':fontsize={size}:fontcolor=white:"
			f"shadowcolor=black@0.45:shadowx=0:shadowy={max(2, height // 360)}:"
			f"x=(w-text_w)/2:y=(h-text_h)/2+h*{offset}:"
			f"alpha='if(lt(t,{appear:.3f}),0,min(1,(t-{appear:.3f})/0.8))'"
		)
	# The title stays readable over a dimmed last shot; the whole frame then fades out.
	if filters:
		filters.insert(0, f"eq=brightness='if(gte(t,{start:.3f}),-0.12*min(1,(t-{start:.3f})/0.8),0)':eval=frame")
	filters.append(f"fade=t=out:st={max(0.0, duration - ENDING_FADE_SECONDS):.3f}:d={ENDING_FADE_SECONDS}")
	_run_ffmpeg(
		[
			"ffmpeg",
			"-y",
			"-i",
			str(source_path),
			"-vf",
			",".join(filters),
			"-an",
			"-c:v",
			"libx264",
			"-profile:v",
			"high",
			"-pix_fmt",
			"yuv420p",
			"-crf",
			"16",
			"-r",
			f"{profile['fps']:g}",
			"-movflags",
			"+faststart",
			str(output_path),
		]
	)


def _has_persisted_positions(clips):
	return all(getattr(clip, "timeline_start_frame", None) is not None for clip in clips)


def _requires_positioned_render(clips, clip_frames):
	cursor = 0
	for clip, frame_count in zip(clips, clip_frames):
		if int(clip.timeline_start_frame or 0) != cursor:
			return True
		cursor += frame_count
	return False


def _delivery_profile(project):
	if not project.workflow:
		frappe.throw(_("Media Project must have a Workflow."))
	workflow = frappe.get_doc("Generation Workflow", project.workflow)
	fps = float(workflow.output_fps or 0)
	if fps <= 0:
		frappe.throw(_("Workflow output FPS must be greater than zero."))
	if not project.delivery_width or not project.delivery_height:
		frappe.throw(_("Media Project must have delivery width and height."))
	return {
		"width": int(project.delivery_width),
		"height": int(project.delivery_height),
		"fps": fps,
	}


def _asset_version_path(asset_version_name):
	asset_version = frappe.get_doc("Asset Version", asset_version_name)
	media_asset = frappe.get_doc("Media Asset", asset_version.media_asset)
	if media_asset.media_type != "Video":
		frappe.throw(_("Timeline source must be a video Asset Version."))
	if not asset_version.file:
		frappe.throw(_("Timeline source Asset Version has no file."))
	file_doc = frappe.get_doc("File", {"file_url": asset_version.file})
	path = Path(file_doc.get_full_path())
	if not path.exists():
		frappe.throw(_("Timeline source file does not exist: {0}").format(path))
	return path


def _get_generated_audio_sources(
	video_clips,
	clip_frames,
	video_duration,
	fps,
	*,
	positioned,
	transition_frames,
):
	sources = []
	cursor = 0
	for index, (clip, frame_count) in enumerate(zip(video_clips, clip_frames)):
		path = _asset_version_path(clip.source_asset_version)
		start_frame = int(clip.timeline_start_frame or 0) if positioned else cursor
		start_seconds = start_frame / fps
		if start_seconds >= video_duration or not _has_audio_stream(path):
			cursor += frame_count - int(transition_frames[index] or 0)
			continue
		source_in_frame = int(clip.source_in_frame or 0)
		source_out_frame = int(clip.source_out_frame or 0)
		sources.append(
			{
				"path": path,
				"start_seconds": start_seconds,
				"source_start_seconds": source_in_frame / fps,
				"duration_seconds": min(
					(source_out_frame - source_in_frame) / fps,
					video_duration - start_seconds,
				),
				"gain_db": 0,
				"fade_in_seconds": 0,
				"fade_out_seconds": 0,
				"duck_others": False,
				"loop": False,
			}
		)
		cursor += frame_count - int(transition_frames[index] or 0)
	return sources


def _normalize_clip(source_path, output_path, profile, source_in_frame, source_out_frame):
	"""Extract a frame-exact source range and normalize it for composition."""
	if source_in_frame < 0 or source_out_frame <= source_in_frame:
		raise ValueError("Invalid source frame range")
	# tpad makes a user-authored out point deterministic even if a generator
	# returned a clip a fraction of a second shorter than its declared length.
	pad_duration = source_out_frame / profile["fps"]
	video_filter = (
		f"fps={profile['fps']:g},"
		f"tpad=stop_mode=clone:stop_duration={pad_duration:.6f},"
		f"trim=start_frame={source_in_frame}:end_frame={source_out_frame},"
		f"setpts=PTS-STARTPTS,"
		f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=increase:flags=lanczos,"
		f"crop={profile['width']}:{profile['height']}"
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
			"-r",
			f"{profile['fps']:g}",
			"-movflags",
			"+faststart",
			str(output_path),
		]
	)


def _validated_transition_frames(clips, clip_frames):
	values = []
	for index, clip in enumerate(clips):
		if index == len(clips) - 1 or (clip.transition_to_next or "Cut") == "Cut":
			values.append(0)
			continue
		if clip.transition_to_next not in TRANSITION_FILTERS:
			raise ValueError(f"Unsupported transition: {clip.transition_to_next}")
		frames = int(clip.transition_frames or 0)
		if frames < 1:
			raise ValueError(f"Transition after clip {clip.name} must be at least one frame")
		if frames >= min(clip_frames[index], clip_frames[index + 1]):
			raise ValueError(f"Transition after clip {clip.name} is longer than a neighboring clip")
		values.append(frames)
	return values


def _render_sequence(paths, clips, clip_frames, transition_frames, output_path, profile, positioned=False):
	if positioned:
		return _render_positioned_sequence(paths, clips, clip_frames, output_path, profile)
	if len(paths) == 1:
		_run_ffmpeg(
			[
				"ffmpeg",
				"-y",
				"-i",
				str(paths[0]),
				"-map",
				"0:v:0",
				"-an",
				"-c:v",
				"libx264",
				"-profile:v",
				"high",
				"-pix_fmt",
				"yuv420p",
				"-movflags",
				"+faststart",
				str(output_path),
			]
		)
		return

	command = ["ffmpeg", "-y"]
	for path in paths:
		command.extend(["-i", str(path)])

	filter_parts = []
	for index in range(len(paths)):
		filter_parts.append(f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS[in{index}]")

	current_label = "in0"
	current_frames = clip_frames[0]
	for index in range(1, len(paths)):
		out_label = f"seq{index}"
		previous_clip = clips[index - 1]
		transition = previous_clip.transition_to_next or "Cut"
		transition_count = transition_frames[index - 1]
		if transition == "Cut" or transition_count == 0:
			filter_parts.append(
				f"[{current_label}][in{index}]concat=n=2:v=1:a=0[{out_label}]"
			)
			current_frames += clip_frames[index]
		else:
			duration = transition_count / profile["fps"]
			offset = (current_frames - transition_count) / profile["fps"]
			transition_filter = TRANSITION_FILTERS[transition]
			filter_parts.append(
				f"[{current_label}][in{index}]xfade=transition={transition_filter}:"
				f"duration={duration:.6f}:offset={offset:.6f}[{out_label}]"
			)
			current_frames += clip_frames[index] - transition_count
		current_label = out_label

	command.extend(
		[
			"-filter_complex",
			";".join(filter_parts),
			"-map",
			f"[{current_label}]",
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
	_run_ffmpeg(command)


def _render_positioned_sequence(paths, clips, clip_frames, output_path, profile):
	"""Render one persisted video track, including gaps before placed clips."""
	command = ["ffmpeg", "-y"]
	for path in paths:
		command.extend(["-i", str(path)])

	filter_parts = []
	labels = []
	previous_end = 0
	for index, (path, clip, frame_count) in enumerate(zip(paths, clips, clip_frames)):
		start = int(clip.timeline_start_frame or 0)
		if start > previous_end:
			gap = start - previous_end
			gap_label = f"gap{index}"
			filter_parts.append(
				f"color=c=black:s={profile['width']}x{profile['height']}:r={profile['fps']:g}:"
				f"d={gap / profile['fps']:.6f}[{gap_label}]"
			)
			labels.append(f"[{gap_label}]")
		clip_label = f"clip{index}"
		filter_parts.append(f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS[{clip_label}]")
		labels.append(f"[{clip_label}]")
		previous_end = start + frame_count

	filter_parts.append(
		f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[video]"
	)
	command.extend(
		[
			"-filter_complex",
			";".join(filter_parts),
			"-map",
			"[video]",
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
	_run_ffmpeg(command)
