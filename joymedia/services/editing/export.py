"""Render the persistent JoyMedia Timeline Clip edit decision list."""

import json
import re
import shutil
import tempfile
from pathlib import Path

import frappe
from frappe import _

from joymedia.services.editing import finishing as finishing
from joymedia.services.editing.composer import (
	_get_audio_sources,
	_get_or_create_final_asset,
	_get_video_duration,
	_mix_audio,
	_run_ffmpeg,
	_validate_normalized_video,
)

STUDIO_EXPORT_QUALITY = "Studio 1440p60"
# Generated clips rarely match the requested length exactly; only a shortfall this large is held.
TAIL_HOLD_MIN_SECONDS = 1
FONT_DIR = Path(frappe.get_app_path("joymedia", "fonts"))
# Every film fades to black, and its sound to silence, over its last half second: the closing packshot stays readable.
ENDING_FADE_SECONDS = 0.5
# Scenes shorter than this get no caption: it would flash by unread.
MIN_CAPTION_SECONDS = 2.0
# A bold sans-serif with Vietnamese letters, on a dark plate: a thin serif disappears on a bright picture.
TITLE_FONT = "DejaVuSans-Bold.ttf"

TRANSITION_FILTERS = {
	"Dissolve": "fade",
	"Fade": "fadeblack",
}


def compose_project_timeline_internal(project_name: str, *, require_brand_approval=False):
	project = frappe.get_doc("Media Project", project_name)
	from joymedia.services.editing.post_production import timeline_signature
	from joymedia.services.editing.timeline import _ensure_source_audio_clips, _timeline_clip_rows

	_timeline_rows = _timeline_clip_rows(project.name)
	_ensure_source_audio_clips(project, _timeline_rows)
	# Source-audio backfill can make a legitimate first-time edit.  Snapshot only
	# after that setup, then refuse to promote a render if the editor changes.
	started_timeline_signature = timeline_signature(project.name)
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
			"shot",
		],
		order_by="clip_order asc, creation asc",
	)
	from joymedia.services.project.versions import export_manifest

	edit_manifest = json.loads(export_manifest(project, clips, started_timeline_signature))
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
	# Authored timelines are held to the requested duration rather than ending at the last clip.
	target_frames = round(float(project.get("total_duration_seconds") or 0) * render["fps"])
	last_end = max(
		(
			int(clip.timeline_start_frame or 0) + frames
			for clip, frames in zip(video_clips, clip_frames, strict=False)
		),
		default=0,
	)
	positioned = _has_persisted_positions(video_clips) and (
		_requires_positioned_render(video_clips, clip_frames)
		or target_frames - last_end >= round(TAIL_HOLD_MIN_SECONDS * render["fps"])
	)
	if positioned:
		for previous, current, previous_frames in zip(
			video_clips, video_clips[1:], clip_frames, strict=False
		):
			previous_end = int(previous.timeline_start_frame or 0) + previous_frames
			if int(current.timeline_start_frame or 0) < previous_end:
				frappe.throw(_("Video clips may not overlap on the single video track."))
		expected_frames = max(last_end, target_frames)
	else:
		expected_frames = sum(clip_frames) - sum(transition_frames)

	# Freeze the renderer's actual timing, including dissolves and positioned gaps.
	# Historical reviews must never be mapped using a project's later storyboard.
	from joymedia.services.review.timeline import rendered_segments

	edit_manifest["render_timeline"] = {
		"segments": rendered_segments(
			video_clips,
			clip_frames,
			transition_frames,
			positioned,
			render["fps"],
			edit_manifest["selected_takes"],
		)
	}

	try:
		with tempfile.TemporaryDirectory(prefix="joymedia-timeline-") as temp_dir:
			temp_path = Path(temp_dir)
			normalized_paths = []
			for index, (clip, frame_count) in enumerate(zip(video_clips, clip_frames, strict=False), start=1):
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
				total_frames=expected_frames,
			)
			_validate_normalized_video(silent_master, render, expected_frames=expected_frames)
			output_frames = expected_frames
			if studio:
				finished_master = temp_path / f"{project.name}-timeline-studio.mp4"
				finishing.finish_video(
					silent_master, finished_master, expected_frames, render["fps"], temp_path
				)
				output_frames = finishing.finished_frame_count(expected_frames, render["fps"])
				_validate_normalized_video(finished_master, output_profile, expected_frames=output_frames)
				silent_master = finished_master
			ended_master = temp_path / f"{project.name}-timeline-ending.mp4"
			cues = _caption_cues(
				project, video_clips, clip_frames, transition_frames, positioned, render["fps"]
			)
			_apply_ending(silent_master, ended_master, output_profile, temp_path, cues)
			_validate_normalized_video(ended_master, output_profile, expected_frames=output_frames)
			silent_master = ended_master

			delivery_path = silent_master
			video_duration = _get_video_duration(silent_master)
			audio_sources = _get_audio_sources(project, video_duration, audio_clips, profile["fps"])
			if audio_sources:
				delivery_path = temp_path / f"{project.name}-timeline.mp4"
				_mix_audio(
					silent_master,
					audio_sources,
					delivery_path,
					ending=(max(0.0, video_duration - ENDING_FADE_SECONDS), ENDING_FADE_SECONDS),
				)
				_validate_normalized_video(delivery_path, output_profile, expected_frames=output_frames)

			from joymedia.services.editing.delivery import delivery_contract, transform_delivery

			delivery = delivery_contract(frappe.get_doc("Generation Workflow", project.workflow))
			if delivery:
				transformed = temp_path / f"{project.name}-delivery-master.mp4"
				output_profile = transform_delivery(delivery_path, transformed, output_profile, delivery)
				_validate_normalized_video(transformed, output_profile, expected_frames=output_frames)
				delivery_path = transformed
				edit_manifest["delivery_transform"] = delivery
			video_duration = _get_video_duration(delivery_path)
			_assert_timeline_unchanged(project.name, started_timeline_signature)
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
	release = None
	if require_brand_approval:
		from joymedia.services.review.release import release_evidence

		# Render inputs must still match the edit after ending the old read snapshot.
		frappe.db.sql("select name from `tabMedia Project` where name=%s for update", project.name)
		frappe.db.sql(
			"select name from `tabTimeline Clip` where media_project=%s order by name for update",
			project.name,
		)
		_assert_timeline_unchanged(project.name, started_timeline_signature)
		try:
			release = release_evidence(project.name, clips, lock=True)
		except ValueError:
			stored_path.unlink(missing_ok=True)
			raise
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
			"release_evidence_json": json.dumps(release) if release else None,
			"edit_manifest_json": json.dumps(edit_manifest, ensure_ascii=False),
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


def _assert_timeline_unchanged(project_name, expected_signature):
	"""Prevent an old render from becoming the project's current delivery."""
	from joymedia.services.editing.post_production import timeline_signature

	if timeline_signature(project_name) != expected_signature:
		frappe.throw(_("The timeline changed during export. Export the latest edit instead."))


PRODUCTION_LABEL = re.compile(r"^\s*(?:cta|vo|v/o|sfx|super|text|txt|chữ|title)\s*[:：-]\s*", re.I)


def caption_text(caption):
	"""The words to show: a sheet's production label in front of them ("CTA: Mua ngay") is a note, not part of the text."""
	return PRODUCTION_LABEL.sub("", str(caption or "")).strip()


def _caption_cues(project, video_clips, clip_frames, transition_frames, positioned, fps):
	"""Return timed (start, end, text) cues for every captioned source shot."""
	if not int(project.get("show_captions") or 0):
		return []
	if not video_clips:
		return []
	shot_names = [clip.get("shot") for clip in video_clips if clip.get("shot")]
	captions = {
		row.name: caption_text(row.caption)
		for row in frappe.get_all("Shot", filters={"name": ["in", shot_names]}, fields=["name", "caption"])
	}
	cues = []
	cursor = 0
	for index, (clip, frame_count) in enumerate(zip(video_clips, clip_frames, strict=False)):
		text = captions.get(clip.get("shot"), "")
		start = int(clip.timeline_start_frame or 0) if positioned else cursor
		if text and frame_count / fps >= MIN_CAPTION_SECONDS:
			cues.append((start / fps, (start + frame_count) / fps, text))
		if not positioned:
			cursor += frame_count - int(transition_frames[index] if index < len(transition_frames) else 0)
	return cues


def _apply_ending(source_path, output_path, profile, temp_path, captions=()):
	"""Draw scene captions and apply an explicitly requested ending fade."""
	duration = _get_video_duration(source_path)
	height = profile["height"]
	filters = []
	for index, (begin, end, text) in enumerate(captions):
		lines = [line.strip() for line in text.splitlines() if line.strip()] or [text]
		size = round(
			min(height * 0.045, profile["width"] * 0.8 / (0.68 * max(max(len(line) for line in lines), 1)))
		)
		show, hide = begin + 0.3, end - 0.3
		if hide - show < 1.0:
			continue
		alpha = (
			f"alpha='if(lt(t,{show:.3f}),0,if(lt(t,{show + 0.5:.3f}),(t-{show:.3f})/0.5,"
			f"if(lt(t,{hide - 0.5:.3f}),1,if(lt(t,{hide:.3f}),({hide:.3f}-t)/0.5,0))))'"
		)
		# One drawtext per line, each centred (this ffmpeg cannot centre the lines of one block), stacked in the top band:
		# the real product pack stands in the lower part of every composition.
		pitch = round(size * 1.6)
		for number, line in enumerate(lines):
			text_file = temp_path / f"caption-{index}-{number}.txt"
			text_file.write_text(line, encoding="utf-8")
			offset = round((number - (len(lines) - 1) / 2) * pitch)
			filters.append(
				f"drawtext=fontfile='{FONT_DIR / TITLE_FONT}':textfile='{text_file}':fontsize={size}:fontcolor=white:"
				f"box=1:boxcolor=black@0.5:boxborderw={round(size * 0.3)}:"
				f"x=(w-text_w)/2:y=h*0.12-text_h/2{offset:+d}:{alpha}"
			)
	# Ending effects must be explicit. An unconditional fade changes a required
	# stable final hold and hides the call to action before the video ends.
	fade_seconds = float(profile.get("ending_fade_seconds") or 0)
	if fade_seconds < 0 or fade_seconds > duration:
		raise ValueError("Ending fade must fit within the exported video.")
	if fade_seconds:
		filters.append(f"fade=t=out:st={duration - fade_seconds:.3f}:d={fade_seconds}")
	_run_ffmpeg(
		[
			"ffmpeg",
			"-y",
			"-i",
			str(source_path),
			"-vf",
			",".join(filters) or "null",
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
	for clip, frame_count in zip(clips, clip_frames, strict=False):
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


def _render_sequence(
	paths, clips, clip_frames, transition_frames, output_path, profile, positioned=False, total_frames=0
):
	if positioned:
		return _render_positioned_sequence(paths, clips, clip_frames, output_path, profile, total_frames)
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
			filter_parts.append(f"[{current_label}][in{index}]concat=n=2:v=1:a=0[{out_label}]")
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


def _render_positioned_sequence(paths, clips, clip_frames, output_path, profile, total_frames=0):
	"""Render one persisted video track.

	Timing gaps are filled by holding the neighbouring picture (the leading gap
	holds the first frame, every later gap and the tail hold the preceding clip's
	last frame) instead of inserting black footage.
	"""
	command = ["ffmpeg", "-y"]
	for path in paths:
		command.extend(["-i", str(path)])

	filter_parts = []
	labels = []
	for index, (clip, frame_count) in enumerate(zip(clips, clip_frames, strict=False)):
		start = int(clip.timeline_start_frame or 0)
		if index + 1 < len(clips):
			next_start = int(clips[index + 1].timeline_start_frame or 0)
		else:
			next_start = max(start + frame_count, int(total_frames or 0))
		hold = max(0, next_start - (start + frame_count))
		lead = start if index == 0 else 0
		pad = ""
		if lead or hold:
			pad = f",tpad=start_mode=clone:start={lead}:stop_mode=clone:stop={hold}"
		clip_label = f"clip{index}"
		filter_parts.append(f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS{pad}[{clip_label}]")
		labels.append(f"[{clip_label}]")

	filter_parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[video]")
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
