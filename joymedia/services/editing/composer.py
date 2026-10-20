"""Assembles the clips of one scene: normalises each generated segment, joins chained segments to the planned length
and levels and mixes their audio; also the audio sources of the timeline export.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _
from frappe.utils.synchronization import filelock


def compose_shot_segments(generation_run_name, shot_name, *, select_output=True):
	"""Assemble completed generated segments into one selected Shot output."""
	with filelock(f"joymedia-compose-shot-{generation_run_name}-{shot_name}"):
		shot = frappe.get_doc("Shot", shot_name)
		all_jobs = frappe.get_all(
			"Generation Task",
			filters={
				"generation_run": generation_run_name,
				"shot": shot.name,
			},
			fields=[
				"name",
				"workflow",
				"segment_index",
				"segment_frame_count",
				"segment_effective_frames",
				"overlap_frames",
				"status",
			],
			order_by="segment_index asc",
		)
		if not all_jobs or any(job.status != "Completed" for job in all_jobs):
			return None
		# A multi-stage pipeline can include image/audio preparation tasks. Only
		# primary-video tasks belong on the visible Shot timeline.
		jobs = [
			job
			for job in all_jobs
			if frappe.db.get_value("Generation Workflow", job.workflow, "output_media_type") == "Video"
		]
		if not jobs:
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
		# Asset allocation must not hold naming/parent locks through media processing.
		frappe.db.commit()
		if not select_output:
			existing = frappe.db.get_value(
				"Asset Version",
				{
					"media_asset": shot_asset.name,
					"source_generation_attempt": segments[-1][1].generation_attempt,
					"source": "Composed",
				},
				"name",
				order_by="creation asc",
			)
			if existing:
				return existing
		if len(segments) == 1:
			profile = _get_delivery_profile(project, generation_run_name)
			expected_frames = _shot_frame_count(shot, profile)
			try:
				with tempfile.TemporaryDirectory(prefix=f"joymedia-shot-{shot.name}-") as temp_dir:
					normalized_path = Path(temp_dir) / f"{shot.name}.mp4"
					_normalize_segment(
						_get_artifact_path(segments[0][1]),
						normalized_path,
						profile,
						int(segments[0][0].segment_frame_count or 0),
						drop_first=False,
						preserve_audio=True,
					)
					_validate_normalized_video(normalized_path, profile, expected_frames=expected_frames)
					normalized_path = _with_locked_product(
						normalized_path, generation_run_name, shot, all_jobs, profile, expected_frames
					)
					normalized_path = _with_closing_hold(
						normalized_path, generation_run_name, shot.name, profile, expected_frames
					)
					normalized_path = _with_graphics(
						normalized_path, generation_run_name, shot.name, profile, expected_frames
					)
					from joymedia.services.review.admission import screen_composition

					can_select = (
						screen_composition(
							normalized_path, generation_run_name, shot.name, segments[-1][1].name
						)
						is not False
					)
					video_bytes = normalized_path.read_bytes()
					video_duration = _get_video_duration(normalized_path)
			except (OSError, subprocess.CalledProcessError, ValueError) as exc:
				frappe.throw(_("Unable to normalize Shot output: {0}").format(_command_error(exc)))
			return _persist_composed_output(
				generation_run_name,
				shot.name,
				shot_asset.name,
				segments[-1][1],
				video_bytes,
				video_duration,
				profile["fps"],
				select_output=select_output,
				can_select=can_select,
			)

		profile = _get_delivery_profile(project, generation_run_name)
		try:
			with tempfile.TemporaryDirectory(prefix=f"joymedia-shot-{shot.name}-") as temp_dir:
				temporary_path = Path(temp_dir)
				normalized_paths = []
				expected_frames = 0
				for index, (job, artifact) in enumerate(segments):
					generated_frames = int(job.segment_frame_count or 0)
					overlap_frames = int(job.overlap_frames or 0) if index > 0 else 0
					effective_frames = int(
						job.segment_effective_frames or (generated_frames - overlap_frames)
					)
					if effective_frames <= 0:
						raise ValueError(f"Generation Task {job.name} has no effective segment frames")
					normalized_path = temporary_path / f"{index + 1:04d}-{job.name}.mp4"
					_normalize_segment(
						_get_artifact_path(artifact),
						normalized_path,
						profile,
						generated_frames,
						drop_first=overlap_frames,
						preserve_audio=True,
					)
					_validate_normalized_video(normalized_path, profile, expected_frames=effective_frames)
					normalized_paths.append(normalized_path)
					expected_frames += effective_frames

				assembled_path = temporary_path / f"{shot.name}.mp4"
				_concatenate_normalized_shots(
					normalized_paths, assembled_path, profile, expected_frames=expected_frames
				)
				_validate_normalized_video(assembled_path, profile, expected_frames=expected_frames)
				assembled_path = _with_locked_product(
					assembled_path, generation_run_name, shot, all_jobs, profile, expected_frames
				)
				assembled_path = _with_closing_hold(
					assembled_path, generation_run_name, shot.name, profile, expected_frames
				)
				assembled_path = _with_graphics(
					assembled_path, generation_run_name, shot.name, profile, expected_frames
				)
				from joymedia.services.review.admission import screen_composition

				can_select = (
					screen_composition(assembled_path, generation_run_name, shot.name, segments[-1][1].name)
					is not False
				)
				video_bytes = assembled_path.read_bytes()
				video_duration = _get_video_duration(assembled_path)
		except (OSError, subprocess.CalledProcessError, ValueError) as exc:
			frappe.throw(_("Unable to assemble Shot segments: {0}").format(_command_error(exc)))

		return _persist_composed_output(
			generation_run_name,
			shot.name,
			shot_asset.name,
			segments[-1][1],
			video_bytes,
			video_duration,
			profile["fps"],
			select_output=select_output,
			can_select=can_select,
		)


def _persist_composed_output(
	run_name, shot_name, asset_name, artifact, content, duration, fps, *, select_output, can_select
):
	"""Promote computed bytes in a short retryable transaction, without replaying QA."""
	from joymedia.services.runtime.transactions import persist_result

	def write():
		if frappe.db.get_value("Generation Run", run_name, "status") == "Cancelled":
			return None
		version = frappe.db.get_value(
			"Asset Version",
			{
				"media_asset": asset_name,
				"source_generation_attempt": artifact.generation_attempt,
				"source": "Composed",
			},
			"name",
			order_by="creation asc",
		)
		if not version:
			file = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"{shot_name}.mp4",
					"content": content,
					"is_private": 1,
					"attached_to_doctype": "Media Asset",
					"attached_to_name": asset_name,
				}
			).insert(ignore_permissions=True)
			version = (
				frappe.get_doc(
					{
						"doctype": "Asset Version",
						"media_asset": asset_name,
						"file": file.file_url,
						"source": "Composed",
						"duration_seconds": duration,
						"fps": fps,
						"source_generation_attempt": artifact.generation_attempt,
						"preservation_evidence_json": None
						if can_select
						else json.dumps(
							{"visual_admission": "Review Required", "generation_artifact": artifact.name}
						),
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		if select_output and can_select:
			_select_output(frappe.get_doc("Shot", shot_name), version)
		return version

	return persist_result(write)


def product_lock_for(generation_run_name, shot_name, jobs):
	"""The product lock of the first frame this scene's video started from: the keyframe drawn in this run, else the
	approved keyframe the run's snapshot names."""
	snapshot = (
		frappe.parse_json(
			frappe.db.get_value("Generation Run", generation_run_name, "project_snapshot_json") or "{}"
		)
		or {}
	)
	row = next((row for row in snapshot.get("shots") or [] if row.get("shot") == shot_name), {})
	frames = [
		r["asset_version"]
		for r in row.get("references") or []
		if frappe.scrub(r.get("reference_role") or r.get("input_role") or "") == "first_frame"
		and r.get("asset_version")
	]
	if frames:
		if len(frames) != 1:
			raise ValueError("A source frame must be unambiguous.")
		from joymedia.services.consistency.repair import _project_asset_path

		project = frappe.get_doc("Media Project", snapshot["media_project"])
		_project_asset_path(project, frames[0])
		frame = frappe.get_doc("Asset Version", frames[0])
		evidence = frappe.parse_json(frame.preservation_evidence_json or "{}") or {}
		lock = evidence.get("product_lock")
		if lock:
			for item in lock.get("items", []):
				patch = item.get("patch_asset_version")
				if not patch:
					raise ValueError("An authored source lock needs an immutable patch asset.")
				_project_asset_path(project, patch)
				if frappe.db.get_value("Asset Version", patch, "file") != item.get("file"):
					raise ValueError("Authored source-lock file does not match its frozen patch.")
		return lock
	for job in jobs:
		if frappe.db.get_value("Generation Workflow", job.workflow, "output_media_type") != "Image":
			continue
		attempt = frappe.db.get_value(
			"Generation Attempt",
			{"generation_task": job.name, "status": "Completed"},
			"name",
			order_by="creation desc",
		)
		lock = (
			frappe.db.get_value(
				"Generation Artifact",
				{"generation_attempt": attempt, "artifact_role": "Primary Image"},
				"product_lock_json",
			)
			if attempt
			else None
		)
		if lock:
			return lock
	snapshot = (
		frappe.parse_json(
			frappe.db.get_value("Generation Run", generation_run_name, "project_snapshot_json") or "{}"
		)
		or {}
	)
	keyframe = next(
		(row.get("keyframe_artifact") for row in snapshot.get("shots") or [] if row.get("shot") == shot_name),
		None,
	)
	return frappe.db.get_value("Generation Artifact", keyframe, "product_lock_json") if keyframe else None


def _with_locked_product(path, generation_run_name, shot, jobs, profile, expected_frames):
	"""The scene's video with the keyframe's exact product pack laid back over every frame (unchanged without one)."""
	from joymedia.services.keyframes.overlay import SourceArtCoverageError, lock_products_in_video

	seconds, _image = _closing_hold_source(generation_run_name, shot.name)
	if seconds >= expected_frames / profile["fps"]:
		# Every output frame will use the frozen source card. Inspecting the
		# discarded generated package first can incorrectly block this repair.
		return path
	snapshot = (
		frappe.parse_json(
			frappe.db.get_value("Generation Run", generation_run_name, "project_snapshot_json") or "{}"
		)
		or {}
	)
	row = next((item for item in snapshot.get("shots") or [] if item.get("shot") == shot.name), {})
	from joymedia.services.consistency.retention import require_coverage

	lock = product_lock_for(generation_run_name, shot.name, jobs)
	require_coverage(row, frappe.parse_json(lock) if isinstance(lock, str) else lock)
	if not lock:
		return path
	locked = path.with_name(f"{path.stem}-locked.mp4")
	try:
		if not lock_products_in_video(path, lock, locked, profile["fps"]):
			raise ValueError("Required source-art product lock produced no protected output.")
	except SourceArtCoverageError:
		from joymedia.services.consistency.repair import track_product_lock

		certificates = track_product_lock(
			path, lock, locked, frappe.get_doc("Media Project", shot.media_project)
		)
		# The normal post-composition visual gate still checks geometry/occlusion.
		from frappe.utils.file_manager import save_file

		save_file(
			f"{generation_run_name}-{shot.name}-tracked-source-art.json",
			json.dumps(certificates, sort_keys=True).encode(),
			"Generation Run",
			generation_run_name,
			is_private=1,
		)
	_validate_normalized_video(locked, profile, expected_frames=expected_frames)
	return locked


def _with_graphics(path, run_name, shot_name, profile, expected_frames):
	from joymedia.services.editing.graphics import apply_graphic_overlays

	snapshot = (
		frappe.parse_json(frappe.db.get_value("Generation Run", run_name, "project_snapshot_json") or "{}")
		or {}
	)
	row = next((item for item in snapshot.get("shots") or [] if item.get("shot") == shot_name), {})
	if not row.get("graphic_overlays"):
		return path
	output = path.with_name(f"{path.stem}-graphics.mp4")
	apply_graphic_overlays(path, row["graphic_overlays"], output, profile, expected_frames)
	_validate_normalized_video(output, profile, expected_frames=expected_frames)
	return output


def _closing_hold_source(run_name, shot_name):
	"""Resolve the actual immutable image condition, never a later edited frame."""
	snapshot = (
		frappe.parse_json(frappe.db.get_value("Generation Run", run_name, "project_snapshot_json") or "{}")
		or {}
	)
	row = next((item for item in snapshot.get("shots") or [] if item.get("shot") == shot_name), {})
	seconds = float(row.get("closing_hold_seconds") or 0)
	if seconds <= 0:
		return 0, None
	if row.get("closing_hold_mode") == "generated_pose":
		return seconds, None
	frames = [
		r["asset_version"]
		for r in row.get("references") or []
		if frappe.scrub(r.get("reference_role") or r.get("input_role") or "") == "first_frame"
		and r.get("asset_version")
	]
	if frames:
		if len(frames) != 1:
			raise ValueError("The closing source frame must be unambiguous.")
		from joymedia.services.consistency.repair import _project_asset_path

		project = frappe.get_doc("Media Project", snapshot["media_project"])
		return seconds, _project_asset_path(project, frames[0])
	keyframe = row.get("keyframe_artifact")
	# The actual dependency wins over a previously approved image in the snapshot.
	for task in frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name, "shot": shot_name},
		fields=["name", "workflow", "depends_on_task", "dependency_artifact_role"],
		order_by="segment_index asc, creation asc",
	):
		if frappe.db.get_value("Generation Workflow", task.workflow, "output_media_type") != "Video":
			continue
		if task.depends_on_task and task.dependency_artifact_role in {"Primary Image", "Last Frame"}:
			keyframe = None
			attempt = frappe.db.get_value(
				"Generation Attempt",
				{"generation_task": task.depends_on_task, "status": "Completed"},
				"name",
				order_by="creation desc",
			)
			if attempt:
				keyframe = frappe.db.get_value(
					"Generation Artifact",
					{"generation_attempt": attempt, "artifact_role": task.dependency_artifact_role},
					"name",
				)
			if not keyframe:
				raise ValueError("The required closing image dependency has no completed artifact.")
		break
	file_url = frappe.db.get_value("Generation Artifact", keyframe, "frappe_file") if keyframe else None
	if not file_url:
		raise ValueError(
			"The required closing artwork has no frozen source image; this take was not protected."
		)
	image = frappe.get_doc("File", {"file_url": file_url}).get_full_path()
	if not Path(image).is_file():
		raise ValueError("The required closing artwork file is unavailable.")
	return seconds, image


def _with_closing_hold(path, run_name, shot_name, profile, expected_frames):
	"""Hold the frozen brand artwork at the end, preserving exact edit length."""
	seconds, image = _closing_hold_source(run_name, shot_name)
	if not seconds:
		return path

	output = path.with_name(f"{path.stem}-held.mp4")
	if image is None:
		# Freeze the actual accepted performance at the hold boundary. Returning
		# to the opening image would erase the action or introduce a pose jump.
		index = max(0, expected_frames - round(seconds * profile["fps"]) - 1)
		image = path.with_name(f"{path.stem}-hold-pose.png")
		subprocess.run(
			[
				"ffmpeg",
				"-v",
				"error",
				"-y",
				"-i",
				str(path),
				"-vf",
				f"select=eq(n\\,{index})",
				"-frames:v",
				"1",
				str(image),
			],
			check=True,
			capture_output=True,
			timeout=60,
		)
	hold_brand_card(path, image, output, profile, expected_frames, seconds)
	_validate_normalized_video(output, profile, expected_frames=expected_frames)
	return output


def hold_brand_card(video, image, output, profile, frames, seconds=2):
	fps, width, height = profile["fps"], profile["width"], profile["height"]
	start = max(0, frames - round(seconds * fps))
	filters = (
		f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[card];"
		f"[0:v][card]overlay=enable='gte(n,{start})':shortest=1[v]"
	)
	subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-y",
			"-i",
			str(video),
			"-loop",
			"1",
			"-framerate",
			str(fps),
			"-i",
			str(image),
			"-filter_complex",
			filters,
			"-map",
			"[v]",
			"-map",
			"0:a?",
			"-frames:v",
			str(frames),
			"-r",
			str(fps),
			"-c:v",
			"libx264",
			"-crf",
			"16",
			"-pix_fmt",
			"yuv420p",
			"-c:a",
			"copy",
			str(output),
		],
		check=True,
		capture_output=True,
		timeout=180,
	)
	return output


def _select_output(shot, asset_version_name):
	"""Select a new immutable take of the scene; reviewers comment on it from there."""
	shot.db_set("selected_output_asset_version", asset_version_name, update_modified=False)
	from joymedia.services.review.consistency import queue_check

	queue_check(shot.name, "take")


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
	spec = frappe.parse_json(workflow.get("execution_spec") or "{}")
	temporal_fit = (spec.get("delivery") or {}).get("temporal_fit", "trim")
	if temporal_fit not in {"trim", "preserve_endpoints"}:
		raise ValueError("Workflow delivery temporal_fit must be trim or preserve_endpoints.")

	return {
		"width": int(width),
		"height": int(height),
		"fps": float(workflow.output_fps),
		"temporal_fit": temporal_fit,
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


SEPARATE_EFFECTS_LAYER = "Separate effects layer"
SCENE_LOUDNESS_LUFS = -18
# Below this mean level (dBFS) a source counts as silent.
AUDIBLE_FLOOR_DB = -55


def _is_audible(path, seconds):
	"""Whether the first `seconds` of an audio source contain real sound."""
	result = subprocess.run(
		[
			"ffmpeg",
			"-v",
			"info",
			"-t",
			f"{seconds:.3f}",
			"-i",
			str(path),
			"-vn",
			"-af",
			"volumedetect",
			"-f",
			"null",
			"-",
		],
		capture_output=True,
		text=True,
	)
	try:
		return float(result.stderr.split("mean_volume:")[1].split("dB")[0]) > AUDIBLE_FLOOR_DB
	except (IndexError, ValueError):
		# -inf (digital silence) or an unreadable stream: nothing to level.
		return False


def _get_audio_sources(project, video_duration, timeline_clips=None, fps=None):
	sources = []
	if timeline_clips is None:
		return sources
	fps = float(fps or 0)
	if fps <= 0:
		frappe.throw(_("Workflow output FPS must be greater than zero."))
	separate_layer = (project.get("soundtrack_mode") if project else None) == SEPARATE_EFFECTS_LAYER
	for clip in timeline_clips:
		# The video model's own audio mixes voice, effects and music in one stream and cannot be split.
		# "Separate effects layer" drops it entirely, leaving just the generated sound-effect layer.
		if separate_layer and clip.audio_role == "Source":
			continue
		start_seconds = float(clip.timeline_start_frame or 0) / fps
		clip_frames = int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0)
		end_seconds = min(start_seconds + clip_frames / fps, video_duration)
		if start_seconds >= video_duration:
			continue
		if end_seconds <= start_seconds:
			frappe.throw(_("Audio clip {0} has no usable timeline duration.").format(clip.name))
		cue_duration = end_seconds - start_seconds
		fade_in_seconds = float(clip.fade_in_frames or 0) / fps
		fade_out_seconds = float(clip.fade_out_frames or 0) / fps
		if fade_in_seconds + fade_out_seconds > cue_duration:
			frappe.throw(_("Audio clip {0} fades exceed its timeline duration.").format(clip.name))
		sources.append(
			{
				"path": _get_timeline_audio_path(clip),
				"start_seconds": start_seconds,
				"duration_seconds": cue_duration,
				"gain_db": float(clip.gain_db or 0),
				"fade_in_seconds": fade_in_seconds,
				"fade_out_seconds": fade_out_seconds,
				"duck_others": bool(clip.duck_others),
				"loop": clip.audio_role == "BGM",
				# Levelling lifts quiet scenes toward a common loudness; a scene with no audible sound must be
				# left silent, not amplified into noise.
				"normalize_loudness": clip.audio_role == "Source"
				and _is_audible(_get_timeline_audio_path(clip), cue_duration),
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


def _get_timeline_audio_path(clip):
	return _get_audio_asset_path(clip.source_asset_version)


def _normalize_segment(
	source_path,
	normalized_path,
	profile,
	generated_frames,
	*,
	drop_first=0,
	preserve_audio=False,
):
	"""Normalize a generated segment and remove its configured overlap frames."""
	drop_first = int(drop_first or 0)
	if drop_first < 0 or drop_first >= generated_frames:
		raise ValueError("drop_first must be smaller than generated_frames")
	effective_frames = generated_frames - drop_first
	audio_filter = ""
	if profile.get("temporal_fit") == "preserve_endpoints":
		from joymedia.services.runtime.media import probe_video

		source = probe_video(source_path)
		drop_source = round(drop_first * source["fps"] / profile["fps"])
		remaining = source["frames"] - drop_source
		if remaining < 2 or effective_frames < 2:
			raise ValueError(
				"Endpoint-preserving temporal fit requires at least two source and output frames."
			)
		video_filter = f"select='gte(n,{drop_source})'," if drop_source else ""
		video_filter += (
			f"setpts=N*{effective_frames - 1}/({remaining - 1}*{profile['fps']:g}*TB),"
			f"tpad=stop_mode=clone:stop_duration={1 / profile['fps']:.9f},fps={profile['fps']:g}:round=near,"
		)
		rate = ((remaining - 1) / source["fps"]) / ((effective_frames - 1) / profile["fps"])
		# FFmpeg's atempo supports 0.5..100; chaining also preserves extreme ratios.
		if drop_source:
			audio_filter = f"atrim=start={drop_source / source['fps']:.9f},asetpts=PTS-STARTPTS,"
		while rate < 0.5 or rate > 2:
			factor = 0.5 if rate < 0.5 else 2
			audio_filter += f"atempo={factor},"
			rate /= factor
		audio_filter += f"atempo={rate:.9f},"
	else:
		video_filter = f"fps={profile['fps']:g},"
		if drop_first:
			video_filter += f"select='gte(n,{drop_first})',"
	video_filter += (
		f"tpad=stop_mode=clone:stop_duration={effective_frames / profile['fps']:.6f},"
		f"trim=end_frame={effective_frames},setpts=PTS-STARTPTS,"
		f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=increase,"
		f"crop={profile['width']}:{profile['height']}"
	)
	command = [
		"ffmpeg",
		"-y",
		"-i",
		str(source_path),
		"-map",
		"0:v:0",
		"-vf",
		video_filter,
	]
	if preserve_audio:
		audio_duration = effective_frames / profile["fps"]
		command.extend(
			[
				"-map",
				"0:a?",
				"-af",
				audio_filter + f"apad,atrim=duration={audio_duration:.6f},asetpts=PTS-STARTPTS",
				"-c:a",
				"aac",
			]
		)
	else:
		command.append("-an")
	command.extend(
		[
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
	_run_ffmpeg(command)


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


def _concatenate_normalized_shots(paths, output_path, profile, expected_frames=None):
	"""Join normalized clips; expected_frames caps the output so audio padding cannot lengthen it."""
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
			"-map",
			"0:a?",
			"-c:v",
			"libx264",
			"-c:a",
			"aac",
			"-profile:v",
			"high",
			"-pix_fmt",
			"yuv420p",
			"-r",
			f"{profile['fps']:g}",
			*(["-t", f"{expected_frames / profile['fps']:.6f}"] if expected_frames else []),
			"-movflags",
			"+faststart",
			str(output_path),
		]
	)


def _mix_audio(silent_master_path, audio_sources, delivery_path, ending=None):
	"""Mix audio_sources under the master; ending=(start, seconds) fades the whole mix out."""
	command = ["ffmpeg", "-y", "-i", str(silent_master_path)]
	filter_parts = []
	duck_labels = []
	base_labels = []
	for index, source in enumerate(audio_sources, start=1):
		if source["loop"]:
			command.extend(["-stream_loop", "-1"])
		command.extend(["-i", str(source["path"])])

		source_start = source.get("source_start_seconds", 0)
		if source_start:
			trim = f"atrim=start={source_start:.6f}:duration={source['duration_seconds']:.6f}"
		else:
			trim = f"atrim=duration={source['duration_seconds']:.6f}"
		filter = f"[{index}:a]{trim},asetpts=PTS-STARTPTS"
		if source.get("normalize_loudness"):
			# Scene audio from different generations varies by tens of dB; bring each scene to a
			# common loudness (EBU R128) with a true-peak ceiling before the user's gain is applied.
			filter += f",loudnorm=I={SCENE_LOUDNESS_LUFS}:TP=-1.5:LRA=11,aformat=sample_rates=48000:channel_layouts=stereo"
		# A mono narration input must not make amix downmix a stereo music bed.
		filter += ",aformat=sample_rates=48000:channel_layouts=stereo"
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
	output_label = "[mixed]"
	if ending:
		start, seconds = ending
		# The audio must span the whole film even when the only sound is a short effect; players handle a
		# stream that ends early badly.
		filter_parts.append(
			f"[mixed]apad=whole_dur={start + seconds:.6f},afade=t=out:st={start:.6f}:d={seconds:.6f}[ending]"
		)
		output_label = "[ending]"
	# Summing individually safe voices/effects can exceed full scale. Protect the
	# final mix with headroom for AAC reconstruction, without automatic makeup gain.
	filter_parts.append(f"{output_label}alimiter=limit=0.707106:level=false:latency=true[delivery_audio]")
	output_label = "[delivery_audio]"
	command.extend(
		[
			"-filter_complex",
			";".join(filter_parts),
			"-map",
			"0:v:0",
			"-map",
			output_label,
			# The master is already normalized H.264; re-encoding would only lose detail.
			"-c:v",
			"copy",
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
	try:
		subprocess.run(command, capture_output=True, text=True, check=True, timeout=600)
	except subprocess.TimeoutExpired as exc:
		raise ValueError("Video processing exceeded the 10-minute timeout.") from exc


def _escape_concat_path(path):
	return str(path).replace("'", "'\\''")


def _command_error(exc):
	if isinstance(exc, subprocess.CalledProcessError):
		return exc.stderr.strip() or str(exc)
	return str(exc)
