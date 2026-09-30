"""Render the persistent JoyMedia Timeline Clip edit decision list."""

import tempfile
from pathlib import Path

import frappe
from frappe import _

from joymedia.services.video_composer import (
	_get_audio_sources,
	_get_or_create_final_asset,
	_get_video_duration,
	_mix_audio,
	_run_ffmpeg,
	_validate_normalized_video,
)


TRANSITION_FILTERS = {
	"Dissolve": "fade",
	"Fade": "fadeblack",
}


def compose_project_timeline_internal(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project.name, "enabled": 1},
		fields=[
			"name",
			"media_specification",
			"clip_order",
			"source_asset_version",
			"source_in_frame",
			"source_out_frame",
			"transition_to_next",
			"transition_frames",
		],
		order_by="clip_order asc, creation asc",
	)
	if not clips:
		frappe.throw(_("The project timeline has no enabled clips."))

	media_specification = frappe.get_doc("Media Specification", clips[0].media_specification)
	if any(clip.media_specification != media_specification.name for clip in clips):
		frappe.throw(_("Timeline clips from different Media Specifications cannot be composed together."))

	profile = _delivery_profile(media_specification)
	clip_frames = [int(clip.source_out_frame) - int(clip.source_in_frame) for clip in clips]
	if any(frames <= 0 for frames in clip_frames):
		frappe.throw(_("Every timeline clip must contain at least one frame."))

	transition_frames = _validated_transition_frames(clips, clip_frames)
	expected_frames = sum(clip_frames) - sum(transition_frames)

	try:
		with tempfile.TemporaryDirectory(prefix="joymedia-timeline-") as temp_dir:
			temp_path = Path(temp_dir)
			normalized_paths = []
			for index, (clip, frame_count) in enumerate(zip(clips, clip_frames), start=1):
				source_path = _asset_version_path(clip.source_asset_version)
				normalized_path = temp_path / f"{index:04d}-{clip.name}.mp4"
				_normalize_clip(
					source_path,
					normalized_path,
					profile,
					int(clip.source_in_frame),
					int(clip.source_out_frame),
				)
				_validate_normalized_video(normalized_path, profile, expected_frames=frame_count)
				normalized_paths.append(normalized_path)

			silent_master = temp_path / f"{project.name}-timeline-silent.mp4"
			_render_sequence(
				normalized_paths,
				clips,
				clip_frames,
				transition_frames,
				silent_master,
				profile,
			)
			_validate_normalized_video(silent_master, profile, expected_frames=expected_frames)

			delivery_path = silent_master
			audio_sources = _get_audio_sources(media_specification, _get_video_duration(silent_master))
			if audio_sources:
				delivery_path = temp_path / f"{project.name}-timeline.mp4"
				_mix_audio(silent_master, audio_sources, delivery_path)
				_validate_normalized_video(delivery_path, profile, expected_frames=expected_frames)

			video_duration = _get_video_duration(delivery_path)
			video_bytes = delivery_path.read_bytes()
	except (OSError, ValueError) as exc:
		frappe.throw(_("Unable to render timeline: {0}").format(str(exc)))
	except Exception as exc:
		# subprocess.CalledProcessError is intentionally folded into a readable
		# editor error without exposing a raw Python traceback to the client.
		stderr = getattr(exc, "stderr", None)
		frappe.throw(_("Unable to render timeline: {0}").format((stderr or str(exc)).strip()))

	output_asset = _get_or_create_final_asset(media_specification)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{project.name}-edited.mp4",
			"content": video_bytes,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": output_asset.name,
		}
	).insert(ignore_permissions=True)

	asset_version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": output_asset.name,
			"file": file_doc.file_url,
			"source": "Edited",
			"duration_seconds": video_duration,
			"fps": profile["fps"],
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
		"final_asset_version": asset_version.name,
		"file": file_doc.file_url,
		"duration_seconds": video_duration,
		"timeline_frames": expected_frames,
		"fps": profile["fps"],
	}


def _delivery_profile(media_specification):
	if not media_specification.workflow:
		frappe.throw(_("Media Specification must have a Workflow."))
	workflow = frappe.get_doc("Workflow", media_specification.workflow)
	fps = float(workflow.output_fps or 0)
	if fps <= 0:
		frappe.throw(_("Workflow output FPS must be greater than zero."))
	if not media_specification.delivery_width or not media_specification.delivery_height:
		frappe.throw(_("Media Specification must have delivery width and height."))
	return {
		"width": int(media_specification.delivery_width),
		"height": int(media_specification.delivery_height),
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


def _render_sequence(paths, clips, clip_frames, transition_frames, output_path, profile):
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
